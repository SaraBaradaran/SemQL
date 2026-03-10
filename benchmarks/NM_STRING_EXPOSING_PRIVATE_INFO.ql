/*
SpotBugs bug descriptions: 
*/

/* Associated Query */

import java

from StringLiteral s
where LLMQuery(s.getValue(), "String exposes private information or credentials")
select s.getValue(), "strings exposing private information"
