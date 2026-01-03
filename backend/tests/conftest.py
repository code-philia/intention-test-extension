"""
Pytest configuration and fixtures for backend tests.
"""
import os
import sys
import pytest

# Add backend directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def setup_env():
    """设置测试所需的环境变量，避免 OpenAI 客户端初始化失败"""
    os.environ.setdefault('OPEN_AI_KEY', 'test-api-key')
    os.environ.setdefault('OPENAI_BASE_URL', 'https://api.test.openai.com/v1')

    # Ensure NLTK stopwords are available for retriever tests.
    try:
        import nltk
        from nltk.corpus import stopwords

        stopwords.words('english')
    except LookupError:
        nltk.download('stopwords', quiet=True)
    yield
