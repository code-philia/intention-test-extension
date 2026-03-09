import java


// determine if a 'caller' calls another 'callee'.
predicate callsRecursively(Callable caller, Callable callee) {
  caller.polyCalls(callee)
}


class TestMethod extends Method {
  TestMethod() {
    this.getLocation().getFile().getAbsolutePath() = "TEST_CASE_ABSOLUTE_PATH"  // NOTO: replace this
  }
}


from Constructor c, TestMethod testM 
 where callsRecursively(testM, c)

select
  c.getDeclaringType(),
  c.getSignature()