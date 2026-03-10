/*
SpotBugs bug descriptions: NM_CLASS_NAMING_CONVENTION
Class names should start with an upper case letter.
Class names should be nouns, in mixed case with the first letter of each internal word capitalized. 
Try to keep your class names simple and descriptive. Use whole words-avoid acronyms and abbreviations (unless the abbreviation is much more widely used than the long form, such as URL or HTML).
*/

/* Associated Query */

import java

from Class c
where c.fromSource() and not c.isAnonymous() and (c.getName().regexpMatch(".*_.*") 
      or not LLMQuery(c.getName(), "Name must be a noun that starts with an upper case letter, in mixed case with the first letter of each internal word capitalized") 
      or not LLMQuery(c.getName(), "Name must be simple and descriptive") 
      or LLMQuery(c.getName(), "Name uses acronyms and abbreviations that are not widely-used"))
select c.getName(), "classes needing modification"
