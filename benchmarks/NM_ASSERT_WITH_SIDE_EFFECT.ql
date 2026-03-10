/*
CodeQueries bug descriptions: An assert statement has a side-effect
All code defined in assert statements is ignored when optimization is requested, that is, the program is run with the -O flag. If an assert statement has any side-effects then the behavior of the program changes when optimization is requested.
*/

/* Associated Query */

import java

from AssertStmt a, Expr e
where e = a.getExpr() and LLMQuery(e.toString(), "Expression has side effect")
select e, a.getFile().getLocation(), "Operation has side-effects"

