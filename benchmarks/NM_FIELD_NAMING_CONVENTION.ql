/*
SpotBugs bug descriptions: NM_FIELD_NAMING_CONVENTION and CI_CONFUSED_INHERITANCE
Names of fields that are not final should be in mixed case with a lowercase first letter and the first letters of subsequent words capitalized. 
Names of final fields should be all uppercase with words separated by underscores.
The class is declared to be final, but declares fields to be protected. Since the class is final, it cannot be derived from, and the use of protected is confusing. The access modifier for the field should be changed to private or public to represent the true use for the field.
*/

/* Associated Query */

import java

from Class c, Field f
where f.getDeclaringType().fromSource() and ((c.isFinal() and f.getDeclaringType() = c and f.isProtected()) or (if f.isFinal() then (not f.getName().regexpMatch("^[A-Z_]+$") or not LLMQuery(f.getName(), "Name must be all uppercase with words separated by underscores")) else not LLMQuery(f.getName(), "Name must be in mixed case with a lowercase first letter and the first letters of subsequent words capitalized")))
select f, "fields needing modification"
