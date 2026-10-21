import java


from SrcCallable c, JavadocText t
where
  c.getFile() = t.getFile() and
  (
    c.getLocation().getStartLine() <= t.getLocation().getStartLine() 
  )
  and
  not exists(SrcCallable c2 | c.getLocation().getFile() = c2.getLocation().getFile() and
      c2.getLocation().getStartLine() <= t.getLocation().getStartLine()
      and
      c2.getLocation().getStartLine() > c.getLocation().getStartLine()
  )
  and (
    t.toString().regexpMatch("(?i).*TODO.*")
    or
    t.toString().regexpMatch("(?i).*FIXME.*")
  ) and
  (
    if c instanceof StaticInitializer
    then LLMQuery(source("file://" + c.getLocation().getFile().getAbsolutePath() + ":" + c.getLocation().getStartLine() + ":" + c.getLocation().getStartColumn() + ":" + (t.getLocation().getEndLine() + 10) + ":0"), "The TODO or FIXME comment [", t.toString(), "] in the above context describes unfinished work that could seriously affect the security or correctness of the software.") 
    else LLMQuery(source(c.getLocation().toString()), source(c.getBody().getLocation().toString()), "The TODO or FIXME comment [", t.toString(), "] in the above context describes unfinished work that could seriously affect the security or correctness of the software.")
  )
select t, t.getLocation()
