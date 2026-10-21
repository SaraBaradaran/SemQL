from tree_sitter import Parser, Language
import tree_sitter_ql
import ast
import re
import sys
import os
from sympy import sympify, true, false
from sympy.logic.boolalg import to_dnf
from sympy.logic.boolalg import And, Or, Not
from sympy import Symbol
import subprocess
from openai import OpenAI
import pandas as pd
import json
import time
import argparse


interm = "/home/sara/java_corpus/queries/interm-q"
final = "/home/sara/java_corpus/queries/final-q"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"

class Oracle():
    def __init__(self):
        self.client = OpenAI()  # API key is read from environment
        self.oracle_calls = 0
        self.oracle_input_tokens = 0
        self.oracle_output_tokens = 0
        self.oracle_time = 0
        self.cach = {}

    def send_prompt(self, prompt):
        response = self.client.chat.completions.create(
            model="gpt-5.6-sol",#"gpt-4o-mini",
            messages=[
              {"role": "user", "content": prompt}
            ],
        )
        answer = response.choices[0].message.content
        self.oracle_input_tokens += response.usage.prompt_tokens
        self.oracle_output_tokens += response.usage.completion_tokens
        #answer = "YES"
        print("-" * 50)
        print(prompt)
        print(answer)
        return answer

    def submit_oracle_queries(self, elements, oracle_var):
        start_time = time.time()
        result = []

        for elem in elements:
            code = " ".join(
                extract_code_from_location(block) if i in source_indices[str(oracle_var)] else block
                for i, block in enumerate(elem.split("::"))
            )

            #code = " ".join(
            #    extract_code_from_location(block) 
            #    if i in source_indices[str(oracle_var)] and os.path.exists(block.split(":")[0]) 
            #    else block
            #    for i, block in enumerate(elem.split("::"))
            #)

            if f"{code}" in self.cach:
                #print(self.cach)
                if self.cach[f"{code}"]:
                   result.append(elem)
                continue
            
            prompt = (
                f"{code}\n"
                "Output YES only if the above proposition holds and "
                "NO otherwise. Do not include extra text in your answer."
            )

            self.oracle_calls += 1

            answer = self.send_prompt(prompt)

            if answer.strip() == "YES":
                self.cach[f"{code}"] = True
                result.append(elem)
            else: self.cach[f"{code}"] = False
            
        self.oracle_time += time.time() - start_time
        return result

class Transforemr(ast.NodeTransformer):
    def visit_UnaryOp(self, node):
        # First rewrite children
        node = self.generic_visit(node)

        if isinstance(node.op, ast.Not):
            operand = node.operand
            # Double negation: not (not X) => X
            if isinstance(operand, ast.UnaryOp) and isinstance(operand.op, ast.Not):
                return operand.operand
            # De Morgan: not (A and B) => (not A) or (not B)
            if isinstance(operand, ast.BoolOp):
                new_op = ast.Or() if isinstance(operand.op, ast.And) else ast.And()
                return ast.BoolOp(
                    op=new_op,
                    values=[
                        ast.UnaryOp(op=ast.Not(), operand=v)
                        for v in operand.values
                    ],
                )
        return node

    def visit_BinOp(self, node):
        # Rewrite children first
        node = self.generic_visit(node)

        # Implication: x >> y  ==>  (not x) or y
        if isinstance(node.op, ast.RShift):
            return ast.BoolOp(
                op=ast.Or(),
                values=[
                    ast.UnaryOp(op=ast.Not(), operand=node.left),
                    node.right
                ]
            )
        return node

class QueryParser:
    def __init__(self, code):
        self.code = code
        self.tree = parser.parse(code)
        self.root = self.tree.root_node

        self.where_root = None
        self.where_clause = None
        self.select_root = None
        self.select_clause = None
        self.from_root = None
        self.from_clause = None
        self.var_types = {}

        self._extract_query_parts()

    # ------------------------------------------------------------------
    # Basic helpers
    # ------------------------------------------------------------------

    def node_text(self, node):
        return self.code[node.start_byte:node.end_byte].decode("utf-8")

    def children_after(self, node):
        """Return the siblings appearing after node."""
        parent = node.parent
        if parent is None:
            return []

        siblings = parent.children
        return siblings[siblings.index(node) + 1:]

    # ------------------------------------------------------------------
    # Query structure extraction
    # ------------------------------------------------------------------

    def _extract_query_parts(self):
        """Extract the FROM, WHERE, and SELECT parts of the query."""
        self._walk(self.root)

    def _walk(self, node):
        if node.type == "where":
            self.where_root = self._get_full_clause(node)
            self.where_clause = self.code[
                node.start_byte:self.where_root.end_byte
            ]

        elif node.type == "select":
            self.select_root = self._get_full_clause(node)
            self.select_clause = self.code[
                node.start_byte:self.select_root.end_byte
            ]

        elif node.type == "from":
            self.from_root = self._get_full_from_clause(node)
            self.from_clause = self.code[
                node.start_byte:self.from_root.end_byte
            ]
            self.var_types = self._extract_var_types(node)

        for child in node.children:
            self._walk(child)

    def _get_full_clause(self, node):
        """Return the complete clause associated with a WHERE or SELECT."""
        for sibling in self.children_after(node):
            if sibling.is_named:
                return sibling

        return node

    def _get_full_from_clause(self, node):
        """Return the complete FROM clause, stopping before WHERE."""
        siblings = self.children_after(node)

        if not siblings:
            return node

        last_sibling = siblings[0]

        for sibling in siblings:
            if self.node_text(sibling) == "where":
                return last_sibling

            last_sibling = sibling

        return last_sibling

    def _extract_var_types(self, from_node):
        """Extract variable names and their declared types from FROM."""
        var_types = {}

        for node in self.children_after(from_node):
            if self.node_text(node) == "where":
                break

            if node.type != "varDecl":
                continue

            type_node = node.child_by_field_name("type")
            name_node = node.child_by_field_name("name")

            if type_node is None or name_node is None:
                continue

            var_types[
                self.node_text(name_node)
            ] = self.node_text(type_node)

        return var_types

    # ------------------------------------------------------------------
    # WHERE-condition parsing
    # ------------------------------------------------------------------

    def parse_where_condition(self, node, vargen):
        """Convert a CodeQL WHERE expression into a Boolean formula."""
        if node is None:
            return None

        node_type = node.type

        if node_type in {
            "quantified",
            "comp_term",
            "call_or_unqual_agg_expr",
            "aritylessPredicateExpr",
            "qualified_expr",
            "instance_of",
            "in_expr",
        }:
            return vargen.fresh(node)

        if node_type in {"conjunction", "disjunction", "implication"}:
            operator = {
                "conjunction": "and",
                "disjunction": "or",
                "implication": ">>",
            }[node_type]

            left = self.parse_where_condition(
                node.child_by_field_name("left"),
                vargen,
            )
            right = self.parse_where_condition(
                node.child_by_field_name("right"),
                vargen,
            )

            return f"({left} {operator} {right})"

        if node_type == "if_term":
            condition = self.parse_where_condition(
                node.child_by_field_name("cond"),
                vargen,
            )
            then_branch = self.parse_where_condition(
                node.child_by_field_name("first"),
                vargen,
            )
            else_branch = self.parse_where_condition(
                node.child_by_field_name("second"),
                vargen,
            )

            return (
                f"(({condition} and {then_branch}) "
                f"or (not {condition} and {else_branch}))"
            )

        if node_type == "negation":
            child = node.named_children[0]
            inner = self.parse_where_condition(child, vargen)
            return f"not {inner}"

        if node_type == "par_expr":
            child = node.named_children[0]
            return f"({self.parse_where_condition(child, vargen)})"

        for child in node.named_children:
            result = self.parse_where_condition(child, vargen)
            if result is not None:
                return result

        return None

    # ------------------------------------------------------------------
    # SELECT extraction
    # ------------------------------------------------------------------

    def extract_select_items(self):
        """Extract individual expressions from the SELECT clause."""
        items = []

        for child in self.select_root.children:
            for item in child.children:
                if item.is_named:
                    items.append(self.node_text(item))

        return items

class SatFormula:
    def __init__(self, formula):
        self.formula = formula

    # ------------------------------------------------------------------
    # Formula normalization
    # ------------------------------------------------------------------

    def push_nots(self):
        """Push negations inward using the Boolean formula transformer."""
        tree = ast.parse(self.formula, mode="eval")
        tree = Transforemr().visit(tree)
        ast.fix_missing_locations(tree)
        return ast.unparse(tree)

    def set_formula(self, formula):
        """Update the stored formula."""
        self.formula = formula

    # ------------------------------------------------------------------
    # AST transformations
    # ------------------------------------------------------------------

    def remove_var_ast(self, node, var):
        """
        Remove all occurrences of `var` from a Boolean AST.

        For example:
            A and var and B  ->  A and B
            A and not var    ->  A
        """
        if isinstance(node, ast.Name):
            return None if node.id == var else node

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            operand = self.remove_var_ast(node.operand, var)
            return self._make_not(operand)

        if isinstance(node, ast.BoolOp):
            values = [
                value
                for child in node.values
                if (value := self.remove_var_ast(child, var)) is not None
            ]
            return self._make_bool_op(node.op, values)

        return node

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_true(node):
        return isinstance(node, ast.Constant) and node.value is True

    @staticmethod
    def _make_not(node):
        if node is None:
            return None

        return ast.UnaryOp(
            op=ast.Not(),
            operand=node,
        )

    @staticmethod
    def _make_bool_op(op, values, empty_value=None):
        if not values:
            return (
                ast.Constant(value=empty_value)
                if empty_value is not None
                else None
            )

        if len(values) == 1:
            return values[0]

        return ast.BoolOp(
            op=op,
            values=values,
        )

    # ------------------------------------------------------------------
    # AST -> string
    # ------------------------------------------------------------------

    def ast_to_str(self, node):
        """Convert a Boolean AST into a CodeQL-compatible expression."""
        if node is None:
            return ""

        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"not {self.ast_to_str(node.operand)}"

        if isinstance(node, ast.BoolOp):
            operator = self._bool_operator(node.op)
            values = [self.ast_to_str(value) for value in node.values]
            return f"({operator.join(values)})"

        if self._is_true(node):
            return "(1 = 1)"

        return str(node)

    @staticmethod
    def _bool_operator(op):
        if isinstance(op, ast.And):
            return " and "
        if isinstance(op, ast.Or):
            return " or "
        raise ValueError(f"Unsupported Boolean operator: {type(op)}")

    # ------------------------------------------------------------------
    # AST -> SymPy expression
    # ------------------------------------------------------------------

    def ast_to_sympy(self, node):
        """Convert a Boolean AST into a SymPy-compatible expression."""
        if node is None:
            return ""

        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"(~{self.ast_to_sympy(node.operand)})"

        if isinstance(node, ast.BoolOp):
            operator = self._sympy_operator(node.op)
            values = [
                self.ast_to_sympy(value)
                for value in node.values
            ]
            return f"({operator.join(values)})"

        if isinstance(node, ast.Constant):
            return repr(node.value)

        return str(node)

    @staticmethod
    def _sympy_operator(op):
        if isinstance(op, ast.And):
            return " & "
        if isinstance(op, ast.Or):
            return " | "
        raise ValueError(f"Unsupported Boolean operator: {type(op)}")

    # ------------------------------------------------------------------
    # SymPy / DNF
    # ------------------------------------------------------------------

    @staticmethod
    def sat_to_dnf(formula):
        """Convert a Boolean expression into DNF."""
        return to_dnf(sympify(formula), simplify=False)

    def sympy_to_and_or_not(self, expr):
        """Convert a SymPy Boolean expression into Python-style syntax."""
        if isinstance(expr, Symbol):
            return expr.name

        if isinstance(expr, Not):
            return f"not ({self.sympy_to_and_or_not(expr.args[0])})"

        if isinstance(expr, And):
            return " and ".join(
                f"({self.sympy_to_and_or_not(arg)})"
                for arg in expr.args
            )

        if isinstance(expr, Or):
            return " or ".join(
                f"({self.sympy_to_and_or_not(arg)})"
                for arg in expr.args
            )

        return str(expr)

    # ------------------------------------------------------------------
    # DNF clause analysis
    # ------------------------------------------------------------------

    @staticmethod
    def clause_contains_term_from_K(clause, K):
        """
        Return the variables from K that occur in a DNF clause,
        regardless of whether they occur positively or negatively.
        """
        literals = clause.args if isinstance(clause, And) else (clause,)

        found = set()

        for literal in literals:
            if isinstance(literal, Symbol) and literal in K:
                found.add(literal)

            elif isinstance(literal, Not) and literal.args[0] in K:
                found.add(literal.args[0])

        return found

    @staticmethod
    def remove_llm_literals(clause, atoms):
        """Return a DNF conjunction with the selected LLM literals removed.

        Algorithm 1 defines F_i[V_i] as the conjunction of *visited*
        LLMQuery literals.  For an unvisited negative literal ``not q``,
        substituting ``q = true`` would incorrectly produce ``false``;
        the literal itself must be omitted instead.
        """
        literals = clause.args if isinstance(clause, And) else (clause,)
        retained = []

        for literal in literals:
            atom = literal.args[0] if isinstance(literal, Not) else literal
            if atom not in atoms:
                retained.append(literal)

        return And(*retained) if retained else true

    def process_dnf_with_K(self, dnf_expr, K):

        # Normalize to simplified DNF.
        dnf_expr = to_dnf(
            dnf_expr,
            simplify=True,
            force=True,
        )

        print(
            f"[-] Simplified DNF: {dnf_expr}",
            file=sys.stderr,
        )

        # Extract individual DNF clauses.
        clauses = (
            list(dnf_expr.args)
            if isinstance(dnf_expr, Or)
            else [dnf_expr]
        )

        annotated_clauses = [
            (clause, self.clause_contains_term_from_K(clause, K))
            for clause in clauses
        ]

        # Algorithm 1 processes *all* DNF terms in increasing order of
        # their number of LLMQuery literals.  In particular, the zero-atom
        # terms precede every term that requires materialization.
        annotated_clauses.sort(key=lambda item: len(item[1]))
        return annotated_clauses


class BoolVarGen:
    def __init__(self):
        self.counter = 0
        self.mapping = {}
        self.cache = {}

    def fresh(self, node):
        """Return a Boolean variable corresponding to a syntax-tree node."""
        key = node.text.decode("utf-8")

        if key in self.cache:
            return self.cache[key]

        self.counter += 1
        variable = f"p{self.counter}"

        self.mapping[variable] = node
        self.cache[key] = variable

        return variable

def rewrite_query(code, ranges):
    """Remove the specified byte ranges from the query."""
    for start, end in sorted(ranges, reverse=True):
        code = code[:start] + code[end:]
    return code


def recover_query(formula, mapping):
    """Replace Boolean variables with their original expressions."""
    for var, expression in mapping.items():
        formula = re.sub(
            rf"\b{re.escape(var)}\b",
            f"({expression})",
            formula,
        )
    return formula


def extract_code_from_location(location: str) -> str:
    """
    Extract the source code corresponding to a CodeQL Location.

    Expected format:
        file:///path/to/File.java:start_line:start_col:end_line:end_col

    Line numbers are 1-based.
    Column numbers are assumed to be 1-based character positions.
    """
    print(location)
    match = re.match(
        r"^file://(.+):(\d+):(\d+):(\d+):(\d+)$",location
    )

    if not match:
        raise ValueError(f"Invalid CodeQL location: {location}")

    file_uri, start_line, start_col, end_line, end_col = match.groups()
    
    file_path = file_uri
    start_line = int(start_line)
    start_col = int(start_col)
    end_line = int(end_line)
    end_col = int(end_col)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ""  # Ignored if file doesn't exist


    if not (1 <= start_line <= len(lines)):
        raise ValueError(f"Invalid start line: {start_line}")

    if not (1 <= end_line <= len(lines)):
        raise ValueError(f"Invalid end line: {end_line}")

    start_line -= 1; end_line -= 1
    start_col -= 1;

    if start_line == end_line:
        return lines[start_line][start_col:end_col]

    return "".join([
        lines[start_line][start_col:],
        *lines[start_line + 1:end_line],
        lines[end_line][:end_col]
    ])


def read_query_file(path):
    with open(path, "rb") as f:
        return f.read()

def parse_llmquery(text):
    """
    Parse an LLMQuery call into its arguments.

    Example:
        LLMQuery(a, b, foo(x, y), "question, here")

    Returns:
        ["a", "b", "foo(x, y)", '"question, here"']

    Each argument may be either a string literal or an arbitrary expression.
    """

    text = text.strip()

    if not text.startswith("LLMQuery(") or not text.endswith(")"):
        raise ValueError(f"Invalid LLMQuery expression: {text}")

    body = text[len("LLMQuery("):-1]

    args = []
    current = []

    depth = 0
    in_string = False
    escape = False

    for ch in body:
        # Inside a string literal
        if in_string:
            current.append(ch)

            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False

            continue

        # Start of a string literal
        if ch == '"':
            in_string = True
            current.append(ch)

        # Opening bracket
        elif ch in "([{":
            depth += 1
            current.append(ch)

        # Closing bracket
        elif ch in ")]}":
            depth -= 1

            if depth < 0:
                raise ValueError(f"Unbalanced brackets in: {text}")

            current.append(ch)

        # Top-level argument separator
        elif ch == "," and depth == 0:
            arg = "".join(current).strip()

            if not arg:
                raise ValueError(f"Empty argument in: {text}")

            args.append(arg)
            current = []

        else:
            current.append(ch)

    if in_string:
        raise ValueError(f"Unterminated string literal in: {text}")

    if depth != 0:
        raise ValueError(f"Unbalanced brackets in: {text}")

    # Add final argument
    arg = "".join(current).strip()

    if not arg:
        raise ValueError(f"Empty final argument in: {text}")

    args.append(arg)

    return args

def parse_llmquery2(text):
    """
    Parse an LLMQuery call into its arguments.

    Example:
        LLMQuery(a, b, foo(x, y), "question, here")

    Returns:
        ["a", "b", "foo(x, y)", '"question, here"']
    """
    text = text.strip()

    if not text.startswith("LLMQuery(") or not text.endswith(")"):
        raise ValueError(f"Invalid LLMQuery expression: {text}")

    body = text[len("LLMQuery("):-1]

    args = []
    current = []

    depth = 0
    in_string = False
    escape = False

    for ch in body:
        # Inside a string literal
        if in_string:
            current.append(ch)

            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False

            continue

        # Start of a string literal
        if ch == '"':
            in_string = True
            current.append(ch)

        # Nested expression
        elif ch in "([{":
            depth += 1
            current.append(ch)

        elif ch in ")]}":
            depth -= 1

            if depth < 0:
                raise ValueError(f"Unbalanced brackets in: {text}")

            current.append(ch)

        # Argument separator
        elif ch == "," and depth == 0:
            arg = "".join(current).strip()

            if not arg:
                raise ValueError(f"Empty argument in: {text}")

            args.append(arg)
            current = []

        else:
            current.append(ch)

    if in_string:
        raise ValueError(f"Unterminated string literal in: {text}")

    if depth != 0:
        raise ValueError(f"Unbalanced brackets in: {text}")

    # Add final argument
    arg = "".join(current).strip()

    if not arg:
        raise ValueError(f"Empty final argument in: {text}")

    args.append(arg)

    return args


start_time = time.time()
if len(sys.argv) < 4:
    print("usage: python script.py <query.ql>")
    sys.exit(1)

#group = sys.argv[1]
#action = sys.argv[2]   
#query_file = sys.argv[3] 
#rest = sys.argv[4:]
parser = argparse.ArgumentParser()
parser.add_argument("--database", required=True)
parser.add_argument("--query", required=True)
cmd_args = parser.parse_args()


code = read_query_file(cmd_args.query)
CodeQL = Language(tree_sitter_ql.language())
parser = Parser(language=CodeQL)
vargen = BoolVarGen()
qp = QueryParser(code)
formula = qp.parse_where_condition(qp.where_root, vargen)
sf = SatFormula(formula)
llm = Oracle()

print(f"[-] SAT Formula: {formula}", file=sys.stderr)


# ------------------------------------------------------------------
# Prepare the formula and identify LLMQuery atoms
# ------------------------------------------------------------------
new_formula = sf.push_nots()
sf.set_formula(new_formula)

select_items = qp.extract_select_items()
variables_to_remove = []

mapping = {}
args = {}
source_indices = {}
oracle_info = {}

print("[-] Var Mapping:", file=sys.stderr)

for var, node in vargen.mapping.items():
    text = code[node.start_byte:node.end_byte].decode("utf-8")

    print(
        f"-------------| {RED}{var} := {text}{RESET}",
        file=sys.stderr,
    )

    mapping[var] = text

    if "LLMQuery" not in text:
        continue

    variables_to_remove.append(var)

    llm_args = parse_llmquery(text)
    print("args = ", llm_args)
    source_indices[var] = [
        i
        for i, arg in enumerate(llm_args)
        if arg.startswith("source(")
    ]
    args[var] = llm_args
    #print("source_indices=", source_indices)


base_args_objects = {
    var: values
    for var, values in args.items()
}

print(base_args_objects)

# ------------------------------------------------------------------
# Convert the formula to DNF
# ------------------------------------------------------------------

tree = ast.parse(new_formula, mode="eval").body
new_sat = sf.ast_to_sympy(tree)

print(
    f"[-] Formula: {new_sat}",
    file=sys.stderr,
)

dnf_expr = sf.sat_to_dnf(new_sat)

print(
    f"[-] DNF Formula: {dnf_expr}",
    file=sys.stderr,
)


# ------------------------------------------------------------------
# Determine which DNF clauses contain LLMQuery atoms
# ------------------------------------------------------------------

oracle_variables = {
    sympify(var)
    for var in variables_to_remove
}
ordered_clauses = sf.process_dnf_with_K(dnf_expr, oracle_variables)
intermediate_queries = 0
dnf_terms = len(ordered_clauses)


# ------------------------------------------------------------------
# Evaluate each intermediate formula
# ------------------------------------------------------------------

previous_clauses = []
materialized_atoms = set()
# O_q in Algorithm 1: regions in which q has already been submitted to
# the oracle (or was excluded by an earlier pruning constraint).
oracle_regions = {q: [] for q in oracle_variables}

for index, (C_i, oracle_atoms) in enumerate(ordered_clauses):
    # A zero-atom DNF term needs no intermediate query, but it must still
    # participate in Delta for every later term.
    if not oracle_atoms:
        previous_clauses.append(C_i)
        continue

    print(f"[-] Processing: {C_i}", file=sys.stderr)
    print(f"[-] Oracle Atoms: {oracle_atoms}", file=sys.stderr)

    oracle_atoms_sorted = sorted(
        oracle_atoms,
        key=lambda p: (
            p not in oracle_info,
            str(p),
        )
    )

    # Oracle predicates that have already been materialized
    visited_oracle_vars = set()
    for oracle_var in oracle_atoms_sorted:
        print(
            f"[-] Let's materialize atom: {oracle_var}",
            file=sys.stderr,
        )

        # This is D_i AND F_i[V_i].  Remove unvisited LLM *literals* from
        # only the current DNF term, so occurrences in Delta are never
        # removed.  In particular, removing ``not q`` is not the same as
        # substituting q = true.
        unvisited_atoms = oracle_atoms - visited_oracle_vars
        current_context = sf.remove_llm_literals(C_i, unvisited_atoms)

        # Delta excludes (1) all preceding DNF terms and (2) every region
        # in O_q for the atom now being materialized (Algorithm 1, 3(c)B).
        #exclusions = list(oracle_regions[oracle_var])
        #if previous_clauses:
        #    exclusions.insert(0, Or(*previous_clauses))
        #relevant_formula = And(
        #    current_context,
        #    *(Not(exclusion) for exclusion in exclusions),
        #)


        # Delta excludes (1) every preceding DNF term and (2) every region
        # in O_q for the atom now being materialized (Algorithm 1, 3(c)B).
        exclusions = [
            *previous_clauses,
            *oracle_regions[oracle_var],
        ]

        relevant_formula = And(
            current_context,
            *(Not(exclusion) for exclusion in exclusions),
        )


        # Render materialized atoms with distinct placeholders.  This is
        # essential when the atom currently being materialized also appears
        # in a preceding term or an O_q region.
        placeholder_map = {
            atom: Symbol(f"materialized_{atom}")
            for atom in materialized_atoms
        }
        rendered_formula = relevant_formula.xreplace(placeholder_map)
        rendered_string = sf.sympy_to_and_or_not(rendered_formula)
        # Keep CodeQL constants in CodeQL syntax: ast_to_str renders a
        # Boolean True as ``(1 = 1)`` rather than Python's ``True``.
        rendered_tree = ast.parse(rendered_string, mode="eval").body
        reduced_formula = sf.ast_to_str(rendered_tree)

        print(
            f"[-] Evaluating: {reduced_formula}",
            file=sys.stderr,
        )

        # Restore ordinary CodeQL expressions.  LLM atoms in this formula
        # are placeholders and are replaced with their materializations below.
        new_query = recover_query(reduced_formula, mapping)
        new_file = (
            f"{interm}/{cmd_args.query.split('/')[-1].split('.ql')[0]}_new_{index}.ql"
        )

        # --------------------------------------------------------------
        # Generate the intermediate CodeQL query
        # --------------------------------------------------------------

        f = open(new_file, "w")
        f.write("import java\n")

        #if visited_oracle_vars:

        f.write("// required predicates must be defined here\n")

        for var in sorted(materialized_atoms, key=str):
            print(f"Let's decide about {var}")
            satisfying_elements = ",".join(
                json.dumps(element, ensure_ascii=False)
                for element in oracle_info[var]
            )

            if satisfying_elements:
                f.write(
                    f"predicate target_predicate_{var}(string arg)"
                )
                f.write("{")
                f.write(
                    f"arg in [{satisfying_elements}]"
                )
                f.write("}\n")

                base_arg = " + \"::\" + ".join(
                    arg[len("source("):-1] if arg.startswith("source(") and arg.endswith(")") else arg
                    for arg in base_args_objects[str(var)]
                )

                new_query = re.sub(
                    rf"\bmaterialized_{re.escape(str(var))}\b",
                    f"target_predicate_{var}({base_arg})",
                    new_query,
                )

            else:
                new_query = re.sub(
                    rf"\bmaterialized_{re.escape(str(var))}\b",
                    "(1 != 1)",
                    new_query,
                )

        f.write(qp.from_clause.decode("utf-8"))
        f.write("\n")

        new_query = new_query.replace("\\", "\\\\")

        if new_query:
            f.write(f"where {new_query}\n")

        # Return the arguments required by the Oracle.
        collection = " + \"::\" + ".join(
            arg[len("source("):-1] if arg.startswith("source(") and arg.endswith(")") else arg
            for arg in base_args_objects[str(oracle_var)]
        )

        select_clause = f"{collection} as target_{oracle_var}" 

        f.write(f"select {select_clause}"); f.close()

        # --------------------------------------------------------------
        # Execute the intermediate CodeQL query
        # --------------------------------------------------------------

        cmd = (
            f"codeql query run {new_file} --database={cmd_args.database} --output=tmp.bqrs"
            #+ " ".join(
            #    option
            #    for option in rest
            #    if not option.startswith("--output=")
            #)
        )

        print(
            f"[-] Int. Query: {cmd}",
            file=sys.stderr,
        )

        subprocess.run(
            ["bash", "-lc", cmd],
            check=True,
            env=os.environ,
        )

        decode_cmd = (
            "codeql bqrs decode "
            "--output=tmp.csv "
            "--format=csv "
            "tmp.bqrs"
        )

        subprocess.run(
            ["bash", "-lc", decode_cmd],
            check=True,
            env=os.environ,
        )

        df = pd.read_csv("tmp.csv")


        # --------------------------------------------------------------
        # Materialize the Oracle atoms returned by this query
        # --------------------------------------------------------------

        target_values = (
            df[f"target_{oracle_var}"]
            .dropna()
            .unique()
            .tolist()
        )
        print(len(target_values))
        if len(target_values) > 80: 
            exit(1)
        target_values = sorted(
            target_values,
            key=str,
        )

        satisfying_values = llm.submit_oracle_queries(
            target_values, oracle_var
        )

        oracle_info.setdefault(oracle_var, []).extend(
            satisfying_values
        )

        # Record D_i AND F_i[V_i] in O_q before q is added to V_i, exactly
        # as the relevant query for q was formed above.
        oracle_regions[oracle_var].append(current_context)
        visited_oracle_vars.add(oracle_var)
        materialized_atoms.add(oracle_var)
        intermediate_queries += 1
        print("Let's add to visited: ", oracle_var)

    previous_clauses.append(C_i)

# ------------------------------------------------------------------
# Construct the final optimized query
# ------------------------------------------------------------------

visited_oracle_vars = (
    sympify(new_sat).free_symbols
    & oracle_info.keys()
)

final_query = code.decode("utf-8")

final_file = (
    #f"final-q/{query_file.split('.ql')[0]}_final.ql"
    f"{final}/{cmd_args.query.split('/')[-1].split('.ql')[0]}_{cmd_args.database.split('/')[-1]}_final.ql"
)
print(final_file)
with open(final_file, "w") as f:

    #if visited_oracle_vars:
    f.write(
        "// required predicates must be defined here\n"
    )

    for var in visited_oracle_vars:

        satisfying_elements = ",".join(
            json.dumps(element, ensure_ascii=False)
            for element in oracle_info[var]
        )

        if satisfying_elements:

            f.write(
                f"predicate target_predicate_{var}(string arg)"
            )
            f.write("{")
            f.write(
                f"arg in [{satisfying_elements}]"
            )
            f.write("}\n")

            base_arg = " + \"::\" + ".join(
                arg[len("source("):-1] if arg.startswith("source(") and arg.endswith(")") else arg
                for arg in base_args_objects[str(var)]
            )

            final_query = final_query.replace(
                mapping[str(var)],
                f"target_predicate_{var}({base_arg})",
            )

        else:
            final_query = final_query.replace(
                mapping[str(var)],
                "(1 != 1)",
            )

    for var in { key for key, value in mapping.items()
                 if "LLMQuery" in value} - {str(var) for var in visited_oracle_vars}:

        final_query = final_query.replace(
            mapping[var],
            "(1 != 1)",
        )

    f.write(final_query)


# ------------------------------------------------------------------
# Execute the final optimized query
# ------------------------------------------------------------------

cmd = (
    f"codeql query run {final_file} --database={cmd_args.database} --output=tmp.bqrs"
    #f"codeql {group} {action} {final_file} "
    #+ " ".join(
    #    option
    #    for option in rest
    #    if not option.startswith("--output=")
    #)
    #+ f" --database={args.database}"
    #+ " --output=tmp.bqrs"
)

print(
    f"[-] Final Query: {cmd}",
    file=sys.stderr,
)

subprocess.run(
    ["bash", "-lc", cmd],
    check=True,
    env=os.environ,
)

decode_cmd = (
    "codeql bqrs decode "
    "--output=tmp.csv "
    "--format=csv "
    "tmp.bqrs"
)

subprocess.run(
    ["bash", "-lc", decode_cmd],
    check=True,
    env=os.environ,
)

df = pd.read_csv("tmp.csv")

print(f"{GREEN}[+] Int. Queries: {intermediate_queries}{RESET}")
print(f"{GREEN}[+] DNF Terms: {dnf_terms}{RESET}")
print(f"{GREEN}[+] Output Tokens: {llm.oracle_output_tokens}{RESET}")
print(f"{GREEN}[+] Input Tokens: {llm.oracle_input_tokens}{RESET}")
print(f"{GREEN}[+] Oracle Calls: {llm.oracle_calls}{RESET}")
print(f"{GREEN}[+] Oracle Time: {llm.oracle_time:.2f}{RESET}")
print(f"{GREEN}[+] Output Tuples: {len(df)}{RESET}")
print(f"{GREEN}[+] Total Time: {time.time() - start_time:.2f}{RESET}")
print(f"See tmp.csv file for the result of SemQL query {sys.argv[3]}")
