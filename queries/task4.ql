import java


from ThrowStmt tr, SrcCallable m, JavadocTag tag
where
  tr.getEnclosingCallable() = m  
  and 
    m.getDoc().getJavadoc().getAChild*() = tag and 
    tag.toString() = "@throws" and
    not LLMQuery( source("file://" + m.getLocation().getFile().getAbsolutePath() + ":" + tag.getLocation().getStartLine() + ":" + tag.getLocation().getStartColumn() + ":" + m.getDoc().getJavadoc().getLocation().getEndLine() + ":" + m.getDoc().getJavadoc().getLocation().getEndColumn() ), source(m.getBody().getLocation().toString()), "The @throws tag above describes triggering conditions that are consistent with the method's implementation.")
select m.getLocation()
