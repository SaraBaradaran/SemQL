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

RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"

class Oracle():
    def __init__(self):
        self.client = OpenAI()  # API key is read from environment
        self.oracle_calls = 0
        self.oracle_input_tokens = 0
        self.oracle_output_tokens = 0
        self.oracle_chunk_calls = 0
        self.oracle_time = 0

    def send_prompt(self, prompt):
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
              {"role": "user", "content": prompt}
            ],
        )
        answer = response.choices[0].message.content
        target_cases = answer.split("\n")
        target_cases = [x.strip() for x in target_cases]
        return target_cases

    def chunk_list(self, lst, size=100):
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    def submit_oracle_queries(self, condition, elements):
        start = time.time()
        chunks = self.chunk_list(elements, 100)
        self.oracle_input_tokens += len(elements)
        ans = []
        self.oracle_calls += 1
        for chunk in chunks:
            self.oracle_chunk_calls += 1
            prompt = f"Task description: Identify if each given case satisfies the following condition: \
            \nCondition: {condition}\
            \nCases: {','.join(str(t) for t in chunk)}\
            \nOutput format: Output all the cases that satisfy the condition. Each satisfying case must be printed on its own line. Do not include extra text or non-satisfying cases."
            #print(prompt)
            ans += self.send_prompt(prompt)
        result = [x for x in ans if "```" not in x]  
        self.oracle_output_tokens += len(result)  
        self.oracle_time += (time.time() - start)
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
        self.tree = parser.parse(code)
        self.root = self.tree.root_node
        self.code = code
        self.walk(self.root)

    def extract_types_from_from_root(self, from_node):
        var_types = {}
        parent = from_node.parent
        siblings = parent.children
        idx = siblings.index(from_node)

        for node in siblings[idx + 1:]:
            if self.node_text(node) == "where": 
                break
            if node.type != "varDecl":
                continue
            type_node = None
            name_node = None
    
            for c in node.children:
                if c.type == "typeExpr":
                    type_node = c
                elif c.type == "varName":
                    # simpleId holds the actual identifier
                    for v in c.children:
                        if v.type == "simpleId":
                            name_node = v
    
            if type_node and name_node:
                type_name = code[type_node.start_byte:type_node.end_byte].decode("utf8")
                var_name = code[name_node.start_byte:name_node.end_byte].decode("utf8")
                var_types[var_name] = type_name
     
        return var_types
     
    def walk(self, node):
        if node.type == "where":
            self.where_root = self.get_full_clause(node, part="where")
            self.where_clause = self.code[node.start_byte:self.where_root.end_byte]
        if node.type == "select":
            self.select_root = self.get_full_clause(node, part="select")
            self.select_clause = self.code[node.start_byte:self.select_root.end_byte]
        if node.type == "from":
            self.from_root = self.get_full_from_clause(node, part="from")
            self.from_clause = self.code[node.start_byte:self.from_root.end_byte]
            self.var_types = self.extract_types_from_from_root(node)
        for c in node.children: 
            self.walk(c)

    def get_full_clause(self, node, part):
        if node.type != part:
            return None
        parent = node.parent
        if not parent:
            return None
        siblings = parent.children
        idx = siblings.index(node)
        for sib in siblings[idx + 1:]:
            if sib.is_named:
                return sib
        return node

    def get_full_from_clause(self, node, part):
        if node.type != part:
            return None
        parent = node.parent
        if not parent:
            return None
        siblings = parent.children
        idx = siblings.index(node)
        last_sib = siblings[idx + 1]
        for sib in siblings[idx + 1:]:
            if self.node_text(sib) == "where":
                return last_sib
            last_sib = sib
        return node

    def node_text(self, node):
        return self.code[node.start_byte:node.end_byte].decode()

    def parse_where_condition(self, node, vargen):
        t = node.type
        if t == "comp_term":
            return vargen.fresh(node)

        if t == "conjunction":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            l = self.parse_where_condition(left, vargen)
            r = self.parse_where_condition(right, vargen)
            return f"({l} and {r})"

        if t == "disjunction":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            l = self.parse_where_condition(left, vargen)
            r = self.parse_where_condition(right, vargen)
            return f"({l} or {r})"

        if t == "implication":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            l = self.parse_where_condition(left, vargen)
            r = self.parse_where_condition(right, vargen)
            return f"({l} >> {r})"

        if t == "if_term":
            cond = node.child_by_field_name("cond")
            then_branch = node.child_by_field_name("first")
            else_branch = node.child_by_field_name("second")
            c = self.parse_where_condition(cond, vargen)
            y = self.parse_where_condition(then_branch, vargen)
            z = self.parse_where_condition(else_branch, vargen)
            return f"(({c} and {y}) or (not {c} and {z}))"

        if t == "negation":
            child = node.named_children[0]
            inner = self.parse_where_condition(child, vargen)
            return f"not {inner}"

        if t == "par_expr":
            child = node.named_children[0]
            return f"({self.parse_where_condition(child, vargen)})"

        if t in { "call_or_unqual_agg_expr", "aritylessPredicateExpr"
            "comp_term", "qualified_expr", "instance_of", "in_expr" }:
            return vargen.fresh(node)

        for c in node.named_children:
            result = self.parse_where_condition(c, vargen)
            if result: return result
        return None

    def extract_select_items(self):
        items = []
        for child in self.select_root.children:
            for item in child.children:
                if not item.is_named:
                    continue
                text = self.code[item.start_byte:item.end_byte].decode("utf8")
                items.append(text)
        return items

class SatFormula:
    def __init__(self, formula):
        self.formula = formula

    def push_nots(self):
        tree = ast.parse(self.formula, mode="eval")
        new_tree = Transforemr().visit(tree)
        ast.fix_missing_locations(new_tree)
        return ast.unparse(new_tree)

    def set_new_formula(self, new_formula):
        self.formula = new_formula

    def remove_var_ast(self, node, var):
        if isinstance(node, ast.Name):
            return None if node.id == var else node
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            new_operand = self.remove_var_ast(node.operand, var)
            return ast.UnaryOp(op=ast.Not(), operand=new_operand) if new_operand else None
        elif isinstance(node, ast.BoolOp):
            new_values = []
            for v in node.values:
                nv = self.remove_var_ast(v, var)
                if nv:
                    new_values.append(nv)
            if not new_values:
                return None
            elif len(new_values) == 1:
                return new_values[0]
            else:
                return ast.BoolOp(op=node.op, values=new_values)
        else: return node

    # Recursively remove a variable from an AST node
    def replace_var_ast(self, node, var):
        if isinstance(node, ast.Name):
            return ast.Constant(value=True) if node.id == var else node
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            new_operand = self.replace_var_ast(node.operand, var)
            if not(isinstance(new_operand, ast.Constant) and new_operand.value is True):
                return ast.UnaryOp(op=ast.Not(), operand=new_operand)
            else:
                return ast.Constant(value=True)
        elif isinstance(node, ast.BoolOp):
            new_values = []
            for v in node.values:
                nv = self.replace_var_ast(v, var)
                new_values.append(nv)
            if not new_values:
                return ast.Constant(value=True)
            elif len(new_values) == 1:
                return new_values[0]
            else:
                return ast.BoolOp(op=node.op, values=new_values)
        else: return node

    # Convert AST back to string
    def ast_to_str(self, node):
        if node is None:
            return ""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"not {self.ast_to_str(node.operand)}"
        elif isinstance(node, ast.BoolOp):
            op_str = ' and ' if isinstance(node.op, ast.And) else ' or '
            return '(' + op_str.join(self.ast_to_str(v) for v in node.values) + ')'
        elif isinstance(node, ast.Constant):
            if node.value is True: return '(1 = 1)'
        else: return str(node)

    def ast_to_sympy(self, node):
        if node is None:
            return ""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"(~ {self.ast_to_sympy(node.operand)})"
        elif isinstance(node, ast.BoolOp):
            op_str = ' & ' if isinstance(node.op, ast.And) else ' | '
            return '(' + op_str.join(self.ast_to_sympy(v) for v in node.values) + ')'
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        else: return str(node)


    def sat_to_dnf(self, formula):
        expr = sympify(formula)
        return to_dnf(expr, simplify=False)

    def sympy_to_and_or_not(self, expr):
        if isinstance(expr, Symbol):
            return expr.name
    
        if isinstance(expr, Not):
            return f"not ({self.sympy_to_and_or_not(expr.args[0])})"
    
        if isinstance(expr, And):
            return " and ".join(
                f"({self.sympy_to_and_or_not(arg)})" for arg in expr.args
            )
    
        if isinstance(expr, Or):
            return " or ".join(
                f"({self.sympy_to_and_or_not(arg)})" for arg in expr.args
            )


    def clause_contains_term_from_K(self, clause, K):
        if isinstance(clause, And):
            literals = clause.args
        else:
            literals = [clause]

        found  = set()
        for lit in literals:
            if isinstance(lit, Symbol) and lit in K:
                found.add(lit)
            if isinstance(lit, Not) and lit.args[0] in K:
                found.add(lit.args[0])   
 
        return found
 
    
    def process_dnf_with_K(self, dnf_expr, K): 
        dnf_expr = to_dnf(dnf_expr, simplify=True, force=True)
        print(f"[-] Simplified DNF: {dnf_expr}", file=sys.stderr)
        if isinstance(dnf_expr, Or):
            clauses = list(dnf_expr.args)
        else:
            clauses = [dnf_expr]
    
        clauses_with_K = []
        clauses_without_K = []
    
        for clause in clauses:
            Kc = self.clause_contains_term_from_K(clause, K)
            if len(Kc):
                clauses_with_K.append((clause, Kc))
            else:
                clauses_without_K.append(clause)
    
        if clauses_without_K:
            W = And(*clauses_without_K)
        else:
            W = false  # edge case
    
        results = []
        clauses_with_K_sorted = sorted( clauses_with_K,
           key=lambda t: len(set(t[0].free_symbols) & K)
        )
        X = [c[0] for c in clauses_with_K_sorted]
        for i, Ci in enumerate(clauses_with_K_sorted):
            Ci, Kc = Ci
            if X[:i]:
                Q = And(*(X[:i]))
            else: Q = false
            P = And(Ci, Not(W))
            results.append((Kc, And(P, Not(Q))))

        return clauses_with_K, clauses_without_K, W, results

def rewrite_query(code, ranges):
    new_code = code
    for start, end in sorted(ranges, reverse=True):
        new_code = new_code[:start] + new_code[end:]
    return new_code

def recover_query(formula, mapping):
    result = formula
    for var, expr in mapping.items():
        result = re.sub(rf'\b{var}\b', f'({expr})', result)
    return result

class BoolVarGen:
    def __init__(self):
        self.i = 0
        self.map = {}
        self.cache = {}

    def freshX(self, node):
        self.i += 1
        name = f"p{self.i}"
        self.map[name] = node
        return name

    def fresh(self, node):
        key = node.text.decode("utf8")
        if key in self.cache:
            return self.cache[key]

        self.i += 1
        name = f"p{self.i}"
        self.map[name] = node
        self.cache[key] = name
        return name


def read_query_file(path):
    with open(path, "rb") as f:
        return f.read()

start_time = time.time()
if len(sys.argv) < 4:
    print("usage: python script.py <query.ql>")
    sys.exit(1)

group = sys.argv[1]
action = sys.argv[2]   
query_file = sys.argv[3] 
rest = sys.argv[4:]

code = read_query_file(query_file)
CodeQL = Language(tree_sitter_ql.language())
parser = Parser(language=CodeQL)
vargen = BoolVarGen()
qp = QueryParser(code)
formula = qp.parse_where_condition(qp.where_root, vargen)
sf = SatFormula(formula)
llm = Oracle()

#print(f"[-] Original Query:", file=sys.stderr)
#print(f"{code.decode('utf8')}", file=sys.stderr)
print(f"[-] SAT Formula: {formula}", file=sys.stderr)

new_formula = sf.push_nots()
sf.set_new_formula(new_formula)
select_items = qp.extract_select_items()
variables_to_remove = []

mapping = {}; args = {}; descs = {}; oracle_info = {}
pattern = re.compile(r'LLMQuery\(\s*([^,]+)\s*,\s*"(.*)"\)')

print(f"[-] Var Mapping:", file=sys.stderr)
for v, n in vargen.map.items():
    text = code[n.start_byte:n.end_byte].decode("utf8")
    print(f"-------------| {RED}{v} := {text}{RESET}", file=sys.stderr)
    mapping[v] = text
    if "LLMQuery" in text: 
        variables_to_remove.append(v)
        m = pattern.search(text)
        if not m: continue
        args[v] = m.group(1)
        descs[v] = m.group(2)

base_args_objects = {}
for k, v in args.items():
    base_args_objects[k] = v

tree = ast.parse(new_formula, mode='eval').body
new_sat = sf.ast_to_sympy(tree)
dnf_expr = sf.sat_to_dnf(new_sat)
print(f"[-] DNF Formula: {dnf_expr}", file=sys.stderr)

V = {sympify(v) for v in variables_to_remove}
clauses_with_K, clauses_without_K, W, results = sf.process_dnf_with_K(dnf_expr, V)
intermediate_queries = len(results)
dnf_terms = len(clauses_with_K) + len(clauses_without_K)

for i, elem in enumerate(results):
   v, c = elem
   print(f"[-] Processing: {c}", file=sys.stderr)
   print(f"[-] Oracle Atoms: {v}", file=sys.stderr)
   formula_symbols = set(c.free_symbols)
   new_formula = sf.sympy_to_and_or_not(c)
   tree = ast.parse(new_formula, mode='eval').body
   new_tree = tree
   for var in v:
       formula_symbols.remove(var)
       new_tree = sf.remove_var_ast(new_tree, str(var))
   new_formula_str = sf.ast_to_str(new_tree)
   print(f"[-] Evaluating: {new_formula_str}", file=sys.stderr)

   new_query = recover_query(new_formula_str, mapping)
   new_file = f"{query_file.split('.ql')[0]}_new_{i}.ql"
      
   known = formula_symbols & oracle_info.keys()

   with open(new_file, "w") as f:
       f.write('import java\n')
       if known:
           f.write('// required predicates must be defined here\n')
           for var in known:
               if var == v: exit(0)
               if satisfying_elements != "":
                   satisfying_elements = ",".join(json.dumps(elem, ensure_ascii=False) for elem in oracle_info[var])
                   f.write(f'predicate target_predicate_{str(var)}(string arg)')
                   f.write('{'); f.write(f'arg in [{satisfying_elements}]'); f.write('}\n')
                   new_query = new_query.replace(mapping[str(var)], f'target_predicate_{str(var)}({base_args_objects[str(var)]})')
               else: 
                   new_query = new_query.replace(mapping[str(var)], f'(1 != 1)')
       f.write(qp.from_clause.decode("utf8") + '\n')
       new_query = new_query.replace("\\", "\\\\")
       if new_query != "": f.write(f'where {new_query}\n')
       s = ','.join(f'{args[str(var)]} as target_{str(var)}' for var in v)
       f.write(f'select {s}')

   cmd = f"codeql {group} {action} {new_file} " + " ".join(f"{option}" for option in rest if not option.startswith("--output=")) + " --output=tmp.bqrs"
   print(f"[-] Int. Query: {cmd}", file=sys.stderr)

   subprocess.run(["bash", "-lc", cmd], check=True, env=os.environ)
   cmd = f"codeql bqrs decode --output=tmp.csv --format=csv tmp.bqrs"   
   subprocess.run(["bash", "-lc", cmd], check=True, env=os.environ)
   df = pd.read_csv("tmp.csv")
   for var in v:
       target_var = df[f"target_{var}"].dropna().unique().tolist()
       target_var = sorted(target_var, key=lambda x: str(x))
       ans_values = llm.submit_oracle_queries(descs[str(var)], target_var)
       if var in oracle_info.keys():
           oracle_info[var] = oracle_info[var] + ans_values
       else: oracle_info[var] = ans_values

known = sympify(new_sat).free_symbols & oracle_info.keys()
final_query = code.decode("utf8")
new_file = f"{query_file.split('.ql')[0]}_final_optimized.ql"

with open(new_file, "w") as f:
    if known:
        f.write('// required predicates must be defined here\n')
        for var in known:
            satisfying_elements = ",".join(json.dumps(elem, ensure_ascii=False) for elem in oracle_info[var])
            if satisfying_elements != "":
                f.write(f'predicate target_predicate_{str(var)}(string arg)')
                f.write('{'); f.write(f'arg in [{satisfying_elements}]'); f.write('}\n')
                final_query = final_query.replace(mapping[str(var)], f'target_predicate_{str(var)}({base_args_objects[str(var)]})')
            else:
                final_query = final_query.replace(mapping[str(var)], f'(1 != 1)')
    f.write(final_query)

cmd = f"codeql {group} {action} {new_file} " + " ".join(f"{option}" for option in rest if not option.startswith("--output=")) + " --output=tmp.bqrs"
print(f"[-] Final Query: {cmd}", file=sys.stderr)

subprocess.run(["bash", "-lc", cmd], check=True, env=os.environ)
cmd = f"codeql bqrs decode --output=tmp.csv --format=csv tmp.bqrs"

subprocess.run(["bash", "-lc", cmd], check=True, env=os.environ)
df = pd.read_csv("tmp.csv")

print(f"{GREEN}[+] Int. Queries: {intermediate_queries}{RESET}")
print(f"{GREEN}[+] DNF Terms: {dnf_terms}{RESET}")
print(f"{GREEN}[+] Output Tokens: {llm.oracle_output_tokens}{RESET}")
print(f"{GREEN}[+] Input Tokens: {llm.oracle_input_tokens}{RESET}")
print(f"{GREEN}[+] Oracle Calls: {llm.oracle_calls}{RESET}")
print(f"{GREEN}[+] Oracle Chunk Calls: {llm.oracle_chunk_calls}{RESET}")
print(f"{GREEN}[+] Oracle Time: {llm.oracle_time:.2f}{RESET}")
print(f"{GREEN}[+] Output Tuples: {len(df)}{RESET}")
print(f"{GREEN}[+] Total Time: {time.time() - start_time:.2f}{RESET}")
print(f"See tmp.csv file for the result of SemQL query {sys.argv[3]}")
