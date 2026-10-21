import java


from AssertStmt assertStmt, MethodCall call
where (call.getAnEnclosingStmt() = assertStmt and 
      (if call.getMethod().fromSource() 
	then LLMQuery("The assertion statement [", source(assertStmt.getLocation().toString()), "] have side effects and potentially changes the state of the program when executed, given that the method [", call.getMethod().getName(), "] is implemented as follows", source(call.getMethod().getBody().getLocation().toString())) 
	else LLMQuery("The assertion statement [", source(assertStmt.getLocation().toString()), "] have side effects and potentially changes the state of the program when executed, given that the method [", call.getMethod().getName(), "] is the one in standard java library packages") ) 
	)
or ( not exists(MethodCall c | c.getAnEnclosingStmt() = assertStmt) and LLMQuery("The assertion statement [", source(assertStmt.getLocation().toString()), "] have side effects and potentially changes the state of the program when executed") )
select assertStmt.toString(), assertStmt.getLocation()
