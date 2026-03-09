import java


// determine if a 'caller' calls another 'callee'.
predicate callsRecursively(Callable caller, Callable callee) {
  caller.polyCalls(callee)
}


from Method targetMethod, Method callerMethod
where callsRecursively(callerMethod, targetMethod)

select
  targetMethod.getDeclaringType(),
  targetMethod.getSignature(), 
  callerMethod.getLocation().getStartLine(),
  callerMethod.getBody().getLocation().getEndLine(),
  callerMethod.getLocation().getFile().getAbsolutePath(),
  callerMethod.getDeclaringType(),
  callerMethod.getSignature()