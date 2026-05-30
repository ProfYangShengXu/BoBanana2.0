from bobanana.language import is_chinese_dominant, language_directive


def test_chinese_detection():
    assert is_chinese_dominant("搜一下 langgraph 最新版本")
    assert is_chinese_dominant("写一个 Python 脚本")
    assert not is_chinese_dominant("create a fib.py script")
    assert "简体中文" in language_directive("搜一下 langgraph")
    assert "Match the user's language" in language_directive("create hello world")


if __name__ == "__main__":
    test_chinese_detection()
    print("test_language PASSED")
