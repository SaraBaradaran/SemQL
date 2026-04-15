/*
CodeQueries bug descriptions: Invalid regular expression pattern
Regular expression patterns that are malformed or syntactically incorrect can lead to runtime errors or unexpected behavior. 
Common issues include unbalanced parentheses, incorrect quantifier placement, invalid character ranges, or unsupported escape sequences.
*/

/* Associated Query */

import java

from MethodAccess call, StringLiteral regex
where ((call.getMethod().getDeclaringType().hasQualifiedName("java.lang", "String") 
      and call.getMethod().getName() in ["matches", "replaceAll", "replaceFirst", "split"]) 
      or 
      (call.getMethod().getDeclaringType().hasQualifiedName("java.util.regex", "Pattern") 
      and call.getMethod().getName() = "compile") 
      or 
      (call.getMethod().getDeclaringType().hasQualifiedName("java.util", "Scanner") 
      and call.getMethod().getName() = "useDelimiter"))
 and regex = call.getArgument(0) and LLMQuery(regex.getValue(), "regex is invalid according to the syntax for regular expressions")
select regex.getValue(), "invalid regex"
