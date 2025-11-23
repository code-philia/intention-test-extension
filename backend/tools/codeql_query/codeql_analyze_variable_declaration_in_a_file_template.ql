import java



class TargetVarDec extends LocalVariableDecl {
  TargetVarDec() {
    this.getLocation().getFile().getAbsolutePath() = "TEST_CASE_ABSOLUTE_PATH"  // NOTE: replace this
  }
}


from TargetVarDec targetVar

select
  targetVar.getType(),
  targetVar.getName(),
  targetVar.getInitializer()
