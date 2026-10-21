import java


from StringLiteral s, Callable enclosing
where s.getValue().regexpMatch("(?i).*(https?|ftps?|file|mailto|wss?)://[a-z0-9\\-._~:/?#\\[\\]@!$&'()*+,;=%]+.*") 
      and enclosing.fromSource()
      and enclosing = s.getEnclosingCallable()
      and s.getFile().getRelativePath().matches("%.java")
      and LLMQuery(source(enclosing.getBody().getLocation().toString()), "The url [", s.getValue(), "] in the above context points to a development, testing, staging, sandbox, mock, local, or otherwise non-production service that should not be used in production")
select s.getValue() as url, s.getLocation()
