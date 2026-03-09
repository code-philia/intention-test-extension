import java


// determine if a 'caller' calls another 'callee'.
predicate callsRecursively(Callable caller, Callable callee) {
  caller.polyCalls(callee)
}


from Constructor targetConstructor, Method callerMethod
where callsRecursively(callerMethod, targetConstructor)

select
  targetConstructor.getDeclaringType(),
  targetConstructor.getSignature(), 
  callerMethod.getLocation().getStartLine(),
  callerMethod.getBody().getLocation().getEndLine(),
  callerMethod.getLocation().getFile().getAbsolutePath(),
  callerMethod.getDeclaringType(),
  callerMethod.getSignature()