"""
Tests for agents.py utility methods.

These tests cover the pure utility functions in the Agent class
that don't require external API calls.
"""


class TestAgentExtractCode:
    """测试 Agent.extract_code_from_response 方法"""

    def test_extract_java_code_block(self):
        """从 ```java 代码块中提取代码"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = '''Here is the code:
```java
public class Test {
    public void test() {
        System.out.println("Hello");
    }
}
```
'''
        result = agent.extract_code_from_response(response)
        assert 'public class Test' in result
        assert 'System.out.println' in result

    def test_extract_plain_code_block(self):
        """从普通 ``` 代码块中提取代码"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = '''Some text
```
def hello():
    print("world")
```
'''
        result = agent.extract_code_from_response(response)
        assert 'def hello()' in result
        assert 'print("world")' in result

    def test_extract_no_code_block_returns_space(self):
        """没有代码块时返回空格"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = 'This is just plain text without any code block.'
        result = agent.extract_code_from_response(response)
        assert result == " "

    def test_extract_multiple_code_blocks_takes_first(self):
        """多个代码块时取第一个"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = '''First block:
```java
class First {}
```
Second block:
```java
class Second {}
```
'''
        result = agent.extract_code_from_response(response)
        assert 'First' in result


class TestAgentLineNumbers:
    """测试 Agent 的行号处理方法"""

    def test_add_line_numbers(self):
        """测试添加行号"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        content = "line1\nline2\nline3"
        result = agent.add_line_numbers(content)
        
        assert result == "1:line1\n2:line2\n3:line3"

    def test_remove_line_numbers(self):
        """测试移除行号"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        content = "1:line1\n2:line2\n3:line3"
        result = agent.remove_line_numbers(content)
        
        assert result == "line1\nline2\nline3"

    def test_add_remove_roundtrip(self):
        """添加后移除应该还原原始内容"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        original = "public class Test {\n    void method() {}\n}"
        
        with_numbers = agent.add_line_numbers(original)
        restored = agent.remove_line_numbers(with_numbers)
        
        assert restored == original


class TestAgentRemoveThinking:
    """测试 Agent.remove_thinking 方法"""

    def test_remove_thinking_with_tag(self):
        """有 </think> 标签时提取标签后的内容"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = "<think>\nSome thinking process\n</think>\nActual answer here"
        result = agent.remove_thinking(response)
        
        assert result == "Actual answer here"

    def test_remove_thinking_no_tag_returns_none(self):
        """没有 </think> 标签时返回 None"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = "Just a normal response without thinking tag"
        result = agent.remove_thinking(response)
        
        assert result is None

    def test_remove_thinking_empty_after_tag(self):
        """标签后为空时返回空字符串"""
        from agents import Agent
        
        agent = Agent('gpt-4o')
        response = "<think>\nThinking...\n</think>\n   "
        result = agent.remove_thinking(response)
        
        assert result == ""


class TestTestDescAgentCheckGeneration:
    """测试 TestDescAgent.check_generation 方法"""

    def test_valid_format_returns_true(self):
        """格式正确时返回 True"""
        from agents import TestDescAgent
        
        agent = TestDescAgent('gpt-4o')
        desc = """# Objective
Test something

# Preconditions
1. Some precondition

# Expected Results
1. Some result
"""
        assert agent.check_generation(desc) is True

    def test_missing_section_returns_false(self):
        """缺少部分时返回 False"""
        from agents import TestDescAgent
        
        agent = TestDescAgent('gpt-4o')
        desc = """# Objective
Test something

# Preconditions
1. Some precondition
"""
        assert agent.check_generation(desc) is False

    def test_duplicate_section_returns_false(self):
        """重复部分时返回 False"""
        from agents import TestDescAgent
        
        agent = TestDescAgent('gpt-4o')
        desc = """# Objective
Test something

# Objective
Another objective

# Preconditions
1. Some precondition

# Expected Results
1. Some result
"""
        assert agent.check_generation(desc) is False


class TestAgentRemoveSingleLineNumber:
    """Test Agent.remove_single_line_number method."""

    def test_removes_line_number(self):
        """Test removing a single line number."""
        from agents import Agent

        agent = Agent.__new__(Agent)
        line = "42:     def foo():"
        result = agent.remove_single_line_number(line)

        # Method returns everything after the first colon
        assert result == "     def foo():"

    def test_line_with_colon_in_content(self):
        """Test line with colon in content returns after first colon."""
        from agents import Agent

        agent = Agent.__new__(Agent)
        line = "10: return {'key': 'value'}"
        result = agent.remove_single_line_number(line)

        assert result == " return {'key': 'value'}"
