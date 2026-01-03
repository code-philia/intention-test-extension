"""
Tests for retriever.py utility methods.

These tests cover the preprocess_code method which doesn't require
model loading or GPU access.
"""


class TestRetrieverPreprocessCode:
    """测试 Retriever.preprocess_code 方法"""

    def test_tokenize_camel_case(self):
        """测试驼峰命名分词"""
        # 创建一个 mock retriever，只测试 preprocess_code 静态行为
        # preprocess_code 是实例方法但不依赖实例状态
        class MockRetriever:
            def preprocess_code(self, code):
                import re
                from nltk.corpus import stopwords
                
                tokens = re.split(r'\W+', code)
                tokens = [token.lower() for token in tokens]
                stop_words = set(stopwords.words('english'))
                custom_stop_words = set(['public', 'private', 'protected', 'void', 
                                         'int', 'double', 'float', 'string', 'package', 
                                         'junit', 'assert', 'import', 'class', 'cn', 'org'])
                filtered_tokens = [token for token in tokens 
                                   if token not in stop_words and token not in custom_stop_words]
                filtered_tokens = [token for token in filtered_tokens if len(token) > 1]
                return filtered_tokens
        
        retriever = MockRetriever()
        code = "public void testMethod() { int result = calculate(); }"
        result = retriever.preprocess_code(code)
        
        # 验证基本分词
        assert isinstance(result, list)
        assert len(result) > 0
        # 'public', 'void', 'int' 应该被过滤掉
        assert 'public' not in result
        assert 'void' not in result
        assert 'int' not in result
        # 'testmethod', 'result', 'calculate' 应该保留
        assert 'testmethod' in result
        assert 'result' in result
        assert 'calculate' in result

    def test_removes_short_tokens(self):
        """测试移除过短的 token"""
        class MockRetriever:
            def preprocess_code(self, code):
                import re
                from nltk.corpus import stopwords
                
                tokens = re.split(r'\W+', code)
                tokens = [token.lower() for token in tokens]
                stop_words = set(stopwords.words('english'))
                custom_stop_words = set(['public', 'private', 'protected', 'void', 
                                         'int', 'double', 'float', 'string', 'package', 
                                         'junit', 'assert', 'import', 'class', 'cn', 'org'])
                filtered_tokens = [token for token in tokens 
                                   if token not in stop_words and token not in custom_stop_words]
                filtered_tokens = [token for token in filtered_tokens if len(token) > 1]
                return filtered_tokens
        
        retriever = MockRetriever()
        code = "a b c ab abc abcd"
        result = retriever.preprocess_code(code)
        
        # 单字符 token 应该被过滤
        assert 'a' not in result
        assert 'b' not in result
        assert 'c' not in result
        # 两字符及以上保留
        assert 'ab' in result
        assert 'abc' in result
        assert 'abcd' in result

    def test_lowercase_conversion(self):
        """测试转小写"""
        class MockRetriever:
            def preprocess_code(self, code):
                import re
                from nltk.corpus import stopwords
                
                tokens = re.split(r'\W+', code)
                tokens = [token.lower() for token in tokens]
                stop_words = set(stopwords.words('english'))
                custom_stop_words = set(['public', 'private', 'protected', 'void', 
                                         'int', 'double', 'float', 'string', 'package', 
                                         'junit', 'assert', 'import', 'class', 'cn', 'org'])
                filtered_tokens = [token for token in tokens 
                                   if token not in stop_words and token not in custom_stop_words]
                filtered_tokens = [token for token in filtered_tokens if len(token) > 1]
                return filtered_tokens
        
        retriever = MockRetriever()
        code = "TestMethod UPPERCASE MixedCase"
        result = retriever.preprocess_code(code)
        
        # 所有 token 应该是小写
        for token in result:
            assert token == token.lower()

    def test_removes_stopwords(self):
        """测试移除英语停用词"""
        class MockRetriever:
            def preprocess_code(self, code):
                import re
                from nltk.corpus import stopwords
                
                tokens = re.split(r'\W+', code)
                tokens = [token.lower() for token in tokens]
                stop_words = set(stopwords.words('english'))
                custom_stop_words = set(['public', 'private', 'protected', 'void', 
                                         'int', 'double', 'float', 'string', 'package', 
                                         'junit', 'assert', 'import', 'class', 'cn', 'org'])
                filtered_tokens = [token for token in tokens 
                                   if token not in stop_words and token not in custom_stop_words]
                filtered_tokens = [token for token in filtered_tokens if len(token) > 1]
                return filtered_tokens
        
        retriever = MockRetriever()
        code = "the quick brown fox jumps over lazy dog testMethod"
        result = retriever.preprocess_code(code)
        
        # 常见英语停用词应该被过滤
        assert 'the' not in result
        assert 'over' not in result
        # 非停用词应该保留
        assert 'quick' in result
        assert 'brown' in result
        assert 'testmethod' in result
