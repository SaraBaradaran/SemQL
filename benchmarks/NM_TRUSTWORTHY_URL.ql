/*
CodeQueries bug descriptions: Incomplete URL substring sanitization
Sanitizing untrusted URLs is a common technique for preventing attacks such as request forgeries and malicious redirections. Usually, this is done by checking that the host of a URL is in a set of allowed hosts. However, treating the URL as a string and checking if one of the allowed hosts is a substring of the URL is very prone to errors. Malicious URLs can bypass such security checks by embedding one of the allowed hosts in an unexpected location.\n\nEven if the substring check is not used in a security-critical context, the incomplete check may still cause undesirable behaviors when the check succeeds accidentally.
*/

/* Associated Query */

import java

from StringLiteral s
where s.getValue().regexpMatch("(?i).*(https?|ftps?|file|mailto|wss?)://[a-z0-9\\-._~:/?#\\[\\]@!$&'()*+,;=%]+.*") 
      and LLMQuery(s.getValue(), "String is an untrustworthy url")
select s.getValue() as url, "url is not trustworthy"
