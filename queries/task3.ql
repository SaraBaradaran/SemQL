import java


from MethodAccess rand, Callable enclosing, MethodAccess caller
where
  ( rand.getMethod().getDeclaringType().hasQualifiedName("java.util", "Random")
    or
    rand.getMethod().hasQualifiedName("java.lang", "Math", "random")
  ) and
  enclosing = rand.getEnclosingCallable() and
  caller.getMethod() = enclosing and 
  LLMQuery(source(enclosing.getLocation().toString()), source(enclosing.getBody().getLocation().toString()), "The value generated using the weak random-number generator [", source(rand.getLocation())  ,"] in the above method has been used for a security-sensitive purpose, such as generating a password, authentication token, session identifier cryptographic key, nonce, verification code, or another value whose unpredictability is important for security. Consider also that the method", enclosing.getName(),  "itself is called in the method below ", source(caller.getEnclosingCallable().getLocation()), source(caller.getEnclosingCallable().getBody().getLocation()))
select rand, rand.getLocation(), enclosing.getName()
