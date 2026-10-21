import java


from Callable m
where
  m.fromSource() and 
  m.getAnAnnotation().getType().hasQualifiedName(
    "java.lang", "Deprecated"
  )
  and (
   not exists(Javadoc d | d = m.getDoc().getJavadoc())
   or
   (
    not exists(JavadocText t | t = m.getDoc().getJavadoc().getAChild*() and t.toString().regexpMatch(".*@link.*")) and 
    not LLMQuery( source(m.getDoc().getJavadoc().getLocation()), "\nThe deprecated method's documentation explicitly recommend an alternative method.")
   )
  )
select m.getLocation()
