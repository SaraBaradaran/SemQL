/*
SpotBugs bug descriptions: NM_METHOD_NAMING_CONVENTION and PI_DO_NOT_REUSE_PUBLIC_IDENTIFIERS_METHOD_NAMES
Method names should start with a lower case letter.
Methods should be verbs, in mixed case with the first letter lowercase, with the first letter of each internal word capitalized.
It is a good practice to avoid reusing public identifiers from the Java Standard Library as method names in your code. 
Doing so can lead to confusion, potential conflicts, and unexpected behavior. 
To maintain code clarity and ensure proper functionality, it is recommended to choose unique and descriptive names for your methods that accurately represent their purpose and differentiate them from standard library identifiers. 
To provide an example, let's say you want to create a method that handles creation of a custom file in your application. 
Instead of using a common name like "File" for the method, which conflicts with the existing java.io.File class, you could choose a more specific and unique name like or "generateFile" or "createOutPutFile". 
A few key points to keep in mind when choosing names as identifier:
Use descriptive names: Opt for descriptive method names that clearly indicate their purpose and functionality. 
This helps avoid shadowing existing Java Standard Library identifiers. For instance, instead of "abs()", consider using "calculateAbsoluteValue()".
Follow naming conventions: Adhere to Java's naming conventions, such as using mixed case for method names. 
Method names should be verbs, with the first letter lowercase and the first letter of each internal word capitalized (e.g. runFast()). 
This promotes code readability and reduces the chances of conflicts.
*/

/* Associated Query */

import java

from Method m
where m.getDeclaringType().fromSource() and (m.getName().regexpMatch(".*_.*") or not LLMQuery(m.getName(), "Name must start with verbs, in mixed case with the first letter lowercase, with the first letter of each internal word capitalized") or LLMQuery(m.getName(), "Name must be among public identifiers from the Java Standard Library, for example <File>, but must not be among method names such as <equals>"))
select m.getName(), "methods needing modification"
