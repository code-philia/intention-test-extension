from ast import arg
import subprocess
from bs4 import BeautifulSoup
import javalang
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

method_lines_jar_path_new = "../javaparser_utils/javaparser-method-lines-1.0-SNAPSHOT-shaded.jar"
method_lines_jar_path_old = "../javaparser_utils/javaparser-method-lines-old-1.0-SNAPSHOT-shaded.jar"
method_calls_jar_path = "../javaparser_utils/javaparser-method-calls-1.0-SNAPSHOT-shaded.jar"
method_calls_cross_jar_path = "../javaparser_utils/javaparser-method-calls-cross-1.0-SNAPSHOT-shaded.jar"
comments_lines_jar_path = "../javaparser_utils/javaparser-comments-lines-1.0-SNAPSHOT-shaded.jar"
unused_classes_del_jar_path = "../javaparser_utils/javaparser-unused-classes-del-1.0-SNAPSHOT-shaded.jar"

def run_result_lines(args):
    # for formality
    # deal with difference of `subprocess.run` output between Windows and Linux
    process = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode != 0:
        logger.error(f'Error running "{args}". The outputs are: \nstderr:\n{process.stderr.decode("utf-8")}stdout:\n{process.stdout.decode("utf-8")}')
    result = process.stdout.decode('utf-8')
    result = result.replace('\r\n', '\n')
    # use `.splitlines()` to avoid the "last line" got from `.split('\n')`
    # and fit cross-platform line breaks
    result_lines = [l for l in result.splitlines()]
    return result_lines

# focal_path = '/bernard/dataset_construction/prep/repos/spark/src/main/java/spark/utils/CollectionUtils.java'
# get mapping between methods and their lines
def get_method_lines(focal_path, new_version = True):
    method_lines_jar_path = method_lines_jar_path_new if new_version else method_lines_jar_path_old
    args = ["java", "-jar", method_lines_jar_path, focal_path]
    
    result_lines = run_result_lines(args)

    method_lines_dic = {}

    # for each line
    for line in result_lines:
        # split by space
        split_line = line.split(" ")
        if len(split_line) < 3:
            continue

        method_name = " ".join(split_line[0:-2])
        starting_line = int(split_line[-2])
        ending_line = int(split_line[-1])

        method_lines_dic[method_name] = (starting_line, ending_line)

    reverse_method_lines_dic = {}

    # create a reverse map that maps line number to method name
    for method_name, (starting_line, ending_line) in method_lines_dic.items():
        for line in range(starting_line, ending_line + 1):
            reverse_method_lines_dic[line] = method_name
    
    return method_lines_dic, reverse_method_lines_dic

def get_expected_focal_method_name(test_method_name, possible_focal_methods):
    test_method_name = test_method_name[test_method_name.index("::::") + 4:]
    if test_method_name.startswith("test") or test_method_name.startswith("Test"):
        test_method_name = test_method_name[4:]
    elif test_method_name.startswith("tests") or test_method_name.startswith("Tests"):
        test_method_name = test_method_name[5:]
    elif test_method_name.endswith("Test") or test_method_name.endswith("test"):
        test_method_name = test_method_name[:-4]
    elif test_method_name.endswith("Tests") or test_method_name.endswith("tests"):
        test_method_name = test_method_name[:-5]
    
    # strip and lowercase
    test_method_name = test_method_name.strip("_").lower()

    # find the method that matches the start of the test_method_name or the end of the test_method_name
    expected_focal_method_name = ""
    for method in possible_focal_methods:
        lowered_method = method.lower()[method.index("::::") + 4:]
        if test_method_name.startswith(lowered_method) or test_method_name.endswith(lowered_method):
            expected_focal_method_name = method
            break
    
    return expected_focal_method_name

def get_method_calls_cross_map(testPath):
    methodCallsMap = {}

    args = ["java", "-jar", method_calls_cross_jar_path, testPath]

    result_lines = run_result_lines(args)

    for line in result_lines:
        split_line = line.split("////")

        if len(split_line) != 2:
            continue

        method_name = split_line[0]

        calls = split_line[-1]

        if len(calls) > 0 and calls[len(calls) - 1] == '----': 
            calls = calls[:len(calls) - 1]
        
        calls = calls.split("----")

        if len(calls) > 0 and calls[-1] == "":
            del calls[-1]
        
        methodCallsMap[method_name] = calls 

    return methodCallsMap

# test_class_name example: utils.CollectionUtilsTest
# test_method_name example: testIsEmpty_whenCollectionIsEmpty_thenReturnTrue
def generate_codecov(base_path, test_class_name, test_method_name):
    args = ["mvn", "clean", "verify", "-Dtest=" + test_class_name + "#" + test_method_name]
    logger.debug(f'Generating code coverage info: {args}')
    # args = ["mvn", "verify", "-Dtest=" + test_class_name + "#" + test_method_name]
    subprocess.run(args, cwd=base_path, stdout=None, stderr=None)

# base_path = '/bernard/dataset_construction/prep/repos/spark'
# test_class_name = 'utils.CollectionUtilsTest'
# test_method_name = 'testIsEmpty_whenCollectionIsEmpty_thenReturnTrue'
# generate and get the relevant jacoco report path
def get_jacoco_report(base_path, test_class_name, test_method_name, org_name, test_suffix):
    # generate codecov
    generate_codecov(base_path, test_class_name, test_method_name)
    # get jacoco report
    # append_path = "spark/" if '.' not in test_class_name else "spark." + '.'.join(test_class_name.split(".")[:-1]) + '/'
    append_path = org_name + "/" if '.' not in test_class_name else org_name + "." + '.'.join(test_class_name.split(".")[:-1]) + '/'
    suff_len = len(test_suffix)
    html_name = test_class_name.split(".")[-1][:suff_len * -1] + ".java.html" # changes from -4 to -5 depending on whether it's Test or Tests
    jacoco_path = base_path + "/target/site/jacoco/" + append_path + html_name
    return jacoco_path

# jacoco_path (path of relevant jacoco report) = '/bernard/dataset_construction/prep/repos/spark/target/site/jacoco/spark/utils/CollectionUtils.java.html'
# get the covered and uncovered lines within the focal file
def get_lines_coverage(jacoco_path):
    with open(jacoco_path) as f:
        soup = BeautifulSoup(f, 'html.parser')
        # find all spans with class 'fc' or 'pc' or 'bpc', and extract the ID
        cov_lines = []
        uncov_lines = []
        for span in soup.find_all('span', class_=['fc', 'pc', 'bpc', 'nc']):
            if span['class'][0] == 'nc':
                uncov_lines.append(int(span['id'][1:]))
            else:
                cov_lines.append(int(span['id'][1:]))
        
        return cov_lines, uncov_lines
    
def annotate_deleted_classes(class_content, unused_classes_lines):
    deleted_lines = []
    for start, end in unused_classes_lines:
        del_lines = range(start - 1, end)
        deleted_lines.extend(del_lines)
    
    class_content_copy = class_content.copy()

    for line in deleted_lines:
        class_content_copy[line] = "<DELETE>" + class_content_copy[line]
    
    return class_content_copy

def delete_irrelevant_methods_and_comments(class_content, irrelevant_methods, foc_method_lines_dic, comment_lines, is_test = False, delete_all_comments = True):
    deleted_lines = []
    for method in irrelevant_methods:
        # print(foc_method_lines_dic, method)
        if method not in foc_method_lines_dic:
            continue
        del_lines = range(foc_method_lines_dic[method][0] - 1, foc_method_lines_dic[method][1])
        deleted_lines.extend(del_lines)
    
    class_content_copy = class_content.copy()

    for line in deleted_lines:
        class_content_copy[line] = "<DELETE>" + class_content_copy[line]
    
    if not is_test and not delete_all_comments:
        # For consecutive comment lines (can just be 1 line), delete all of them if the next line has been annotated <DELETE>
        i = 0
        while i < len(class_content_copy) - 1:
            if class_content_copy[i].startswith("<DELETE>") and i in comment_lines:
                j = i
                while j >= 1 and j in comment_lines:
                    class_content_copy[j - 1] = "<DELETE>" + class_content_copy[j - 1]
                    j -= 1
            i += 1

        # Delete comments if there is any non ascii characters inside
        i = 0
        while i < len(class_content_copy) - 1:
            j = i
            if i in comment_lines and (not class_content_copy[i - 1].isascii() or "Copyright" in class_content_copy[i - 1] or "copyright" in class_content_copy[i - 1]):
                j = i - 1
                while j > 0 and j in comment_lines:
                    class_content_copy[j - 1] = "<DELETE>" + class_content_copy[j - 1]
                    j -= 1
                j = i
                while j < len(class_content_copy) and j in comment_lines:
                    class_content_copy[j - 1] = "<DELETE>" + class_content_copy[j - 1]
                    j += 1
            if i == j:
                i += 1
            else:
                i = j
    else:
        # delete all comments
        i = 0
        while i < len(class_content_copy) + 1:
            if i in comment_lines:
                class_content_copy[i - 1] = "<DELETE>" + class_content_copy[i - 1]
            i += 1

    if is_test:
        # Delete test annotations (defined as block comments that contains @author)
        i = 0
        while i < len(class_content_copy) - 1:
            j = i
            if i in comment_lines and "@author" in class_content_copy[i - 1]:
                j = i - 1
                while j > 0 and j in comment_lines:
                    class_content_copy[j - 1] = "<DELETE>" + class_content_copy[j - 1]
                    j -= 1
                j = i
                while j < len(class_content_copy) and j in comment_lines:
                    class_content_copy[j - 1] = "<DELETE>" + class_content_copy[j - 1]
                    j += 1
            if i == j:
                i += 1
            else:
                i = j

    # now actually delete
    i = 0
    while i < len(class_content_copy):
        if class_content_copy[i].startswith("<DELETE>"):
            del class_content_copy[i]
        else:
            i += 1

    return class_content_copy

def delete_consecutive_empty_lines(class_content):
    i = 0
    while i < len(class_content) - 1:
        if class_content[i].strip() == "" and class_content[i + 1].strip() == "":
            del class_content[i]
        else:
            i += 1
            
    return class_content

def get_irrelevant_methods(method_call_map, focal_method):
    all_methods = set(method_call_map.keys())

    relevant_methods = set()

    relevant_methods.add(focal_method)

    for method in method_call_map[focal_method]:
        relevant_methods.add(method)

    for method, called_methods in method_call_map.items():
        if focal_method in called_methods:
            relevant_methods.add(method)

    return all_methods - relevant_methods

def get_comment_lines(filepath):
    comment_lines = []

    args = ["java", "-jar", comments_lines_jar_path, filepath]

    result_lines = run_result_lines(args)

    for line in result_lines:
        if not line.strip():
            continue
        try:
            comment_lines.append(int(line))
        except:
            pass
    
    return comment_lines

def get_method_calls_map(filepath):
    methodCallsMap = {}

    args = ["java", "-jar", method_calls_jar_path, filepath]

    result_lines = run_result_lines(args)

    for line in result_lines:
        split_line = line.split("////")

        if len(split_line) != 2:
            continue

        method_name = split_line[0]

        calls = split_line[-1]

        if len(calls) > 0 and calls[len(calls) - 1] == '----': 
            calls = calls[:len(calls) - 1]
        
        calls = calls.split("----")

        if len(calls) > 0 and calls[-1] == "":
            del calls[-1]
        
        methodCallsMap[method_name] = calls 

    return methodCallsMap

def get_unused_classes_lines(filepath):
    args = ["java", "-jar", unused_classes_del_jar_path, filepath]

    result_lines = run_result_lines(args)
    # print(args)

    dic = {}

    # example result: ExceptionKit::::getCause()////49-52,,,,44-47,,,,29-32,,,,58-62,,,,34-37,,,,39-42,,,,54-71,,,,

    for line in result_lines:
        split_line = line.split("////")

        if len(split_line) != 2:
            continue

        class_name = split_line[0]

        lines = split_line[-1]

        if len(lines) > 0 and lines[len(lines) - 1] == ',,,,': 
            lines = lines[:len(lines) - 1]
        
        lines = lines.split(",,,,")

        if len(lines) > 0 and lines[-1] == "":
            del lines[-1]
        
        temp = [x.split("-") for x in lines]
        dic[class_name] = [[int(x) for x in y] for y in temp]
    
    # print(dic)
    return dic

def type_to_str(t):
    """
    Convert a javalang type node into its Java source code representation.
    Supports both BasicType and ReferenceType, including type arguments and dimensions.
    """
    if t is None:
        return ""
    if isinstance(t, javalang.tree.BasicType):
        type_str = t.name
    elif isinstance(t, javalang.tree.ReferenceType):
        type_str = t.name
        if t.arguments:
            args_str = ", ".join(type_argument_to_str(arg) for arg in t.arguments)
            type_str += f"<{args_str}>"
    else:
        type_str = str(t)
    if hasattr(t, 'dimensions') and t.dimensions:
        type_str += "[]" * len(t.dimensions)
    return type_str


def type_argument_to_str(arg):
    """
    Convert a TypeArgument node to its source code representation.
    If the argument represents a wildcard (i.e. its type is None), simply return "?".
    Otherwise, if a bound is specified, include it.
    """
    if isinstance(arg, javalang.tree.TypeArgument):
        # Wildcard with no bound, e.g. <?>
        if arg.type is None:
            return "?"
        # Wildcard with a bound, e.g. <? extends Number>
        if arg.pattern_type:
            return f"? {arg.pattern_type} {type_to_str(arg.type)}"
        else:
            return type_to_str(arg.type)
    else:
        return type_to_str(arg)


def format_parameter(param):
    """
    Format a method or constructor parameter, including modifiers such as 'final'.
    """
    mods = ""
    if param.modifiers and "final" in param.modifiers:
        mods = "final "
    type_str = type_to_str(param.type)
    return f"{mods}{type_str} {param.name}"

def expr_to_str(expr):
    """
    Convert an expression node back into Java source code.
    This function handles literals, member references, method invocations,
    array initializers/creators, class creators, class references, binary
    and ternary expressions.
    """
    if expr is None:
        return ""
    if isinstance(expr, javalang.tree.Literal):
        return expr.value
    elif isinstance(expr, javalang.tree.MemberReference):
        qualifier = f"{expr.qualifier}." if expr.qualifier else ""
        return f"{qualifier}{expr.member}"
    elif isinstance(expr, javalang.tree.MethodInvocation):
        qualifier = f"{expr.qualifier}." if expr.qualifier else ""
        args = ", ".join(expr_to_str(arg) for arg in expr.arguments)
        return f"{qualifier}{expr.member}({args})"
    elif isinstance(expr, javalang.tree.ArrayInitializer):
        elements = ", ".join(expr_to_str(e) for e in expr.initializers)
        return f"{{ {elements} }}"
    elif isinstance(expr, javalang.tree.ArrayCreator):
        type_str = type_to_str(expr.type)
        dims = "[]" * len(expr.dimensions) if expr.dimensions else ""
        initializer = ""
        if expr.initializer is not None:
            initializer = " " + expr_to_str(expr.initializer)
        return f"new {type_str}{dims}{initializer}"
    elif isinstance(expr, javalang.tree.ClassCreator):
        type_str = type_to_str(expr.type)
        args = ", ".join(expr_to_str(arg) for arg in expr.arguments)
        return f"new {type_str}({args})"
    elif isinstance(expr, javalang.tree.ClassReference):
        # Handle class literals like CronConverter.class
        return f"{type_to_str(expr.type)}.class"
    elif isinstance(expr, javalang.tree.BinaryOperation):
        left = expr_to_str(expr.operandl)
        right = expr_to_str(expr.operandr)
        return f"{left} {expr.operator} {right}"
    elif isinstance(expr, javalang.tree.TernaryExpression):
        cond = expr_to_str(expr.condition)
        if_true = expr_to_str(expr.if_true)
        if_false = expr_to_str(expr.if_false)
        return f"{cond} ? {if_true} : {if_false}"
    else:
        return str(expr)

def order_modifiers(modifiers):
    """
    Order modifiers according to conventional Java ordering.
    """
    order = ['public', 'protected', 'private', 'abstract', 'static', 'final',
             'transient', 'volatile', 'synchronized', 'native', 'strictfp']
    sorted_mods = sorted(modifiers, key=lambda x: order.index(x) if x in order else 100)
    return " ".join(sorted_mods)

def process_type(type_decl, indent=""):
    """
    Process a class or interface declaration (including inner types) and return its skeleton as a list of lines.
    """
    lines = []
    # Build the header line with modifiers, type keyword, name, type parameters,
    # and extends/implements clauses.
    modifiers = order_modifiers(type_decl.modifiers) + " " if type_decl.modifiers else ""
    type_keyword = "class" if isinstance(type_decl, javalang.tree.ClassDeclaration) else "interface"
    header = f"{indent}{modifiers}{type_keyword} {type_decl.name}"
    if hasattr(type_decl, 'type_parameters') and type_decl.type_parameters:
        tparams = ", ".join(tp.name for tp in type_decl.type_parameters)
        header += f"<{tparams}>"
    if isinstance(type_decl, javalang.tree.ClassDeclaration):
        if type_decl.extends is not None:
            header += " extends " + type_to_str(type_decl.extends)
        if type_decl.implements:
            header += " implements " + ", ".join(type_to_str(t) for t in type_decl.implements)
    elif isinstance(type_decl, javalang.tree.InterfaceDeclaration):
        if type_decl.extends:
            header += " extends " + ", ".join(type_to_str(t) for t in type_decl.extends)
    header += " {"
    lines.append(header)

    # Process fields
    for field in type_decl.fields:
        mod_field = order_modifiers(field.modifiers) + " " if field.modifiers else ""
        field_type = type_to_str(field.type)
        declarators = []
        for declarator in field.declarators:
            decl = declarator.name
            if declarator.initializer is not None:
                decl += " = " + expr_to_str(declarator.initializer)
            declarators.append(decl)
        decls_str = ", ".join(declarators)
        lines.append(f"{indent}    {mod_field}{field_type} {decls_str};")
    if type_decl.fields:
        lines.append("")

    # Process constructors (only for classes)
    if isinstance(type_decl, javalang.tree.ClassDeclaration):
        for constructor in type_decl.constructors:
            mod_ctor = order_modifiers(constructor.modifiers) + " " if constructor.modifiers else ""
            params = ", ".join(format_parameter(param) for param in constructor.parameters)
            lines.append(f"{indent}    {mod_ctor}{type_decl.name}({params})")

    # Process methods
    for method in type_decl.methods:
        mod_method = order_modifiers(method.modifiers) + " " if method.modifiers else ""
        return_type = type_to_str(method.return_type) if method.return_type else "void"
        params = ", ".join(format_parameter(param) for param in method.parameters)
        end_char = ";" if isinstance(type_decl, javalang.tree.InterfaceDeclaration) else ""
        lines.append(f"{indent}    {mod_method}{return_type} {method.name}({params}){end_char}")

    # Process inner types (if any) found in the body.
    if hasattr(type_decl, 'body'):
        for element in type_decl.body:
            if isinstance(element, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                lines.append("")  # add a blank line before inner type
                inner_lines = process_type(element, indent + "    ")
                lines.extend(inner_lines)

    lines.append(f"{indent}}}")
    return lines

def skeletonize_java_code(java_code):
    tree = javalang.parse.parse(java_code)
    lines = []
    # Package declaration
    if tree.package:
        lines.append(f"package {tree.package.name};\n")
    # Import declarations
    for imp in tree.imports:
        line = "import "
        if imp.static:
            line += "static "
        line += imp.path
        if imp.wildcard:
            line += ".*"
        line += ";"
        lines.append(line)
    if tree.imports:
        lines.append("")

    # Process each top-level type
    for type_decl in tree.types:
        type_lines = process_type(type_decl)
        lines.extend(type_lines)
        lines.append("")  # blank line between top-level types

    return "\n".join(lines)