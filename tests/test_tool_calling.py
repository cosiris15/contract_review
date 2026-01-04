#!/usr/bin/env python3
"""
AI工具调用功能测试脚本

用途：测试从用户消息到AI工具调用到文档修改的完整流程
"""
import sys
import os

# 添加后端路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

def test_tool_system():
    """测试1: 工具系统基础功能"""
    print("\n" + "="*60)
    print("测试1: 工具系统基础功能")
    print("="*60)

    try:
        from src.contract_review.document_tools import DOCUMENT_TOOLS, DocumentToolExecutor

        print(f"✅ 工具加载成功: {len(DOCUMENT_TOOLS)} 个工具")

        for tool in DOCUMENT_TOOLS:
            name = tool['function']['name']
            params = list(tool['function']['parameters']['properties'].keys())
            print(f"  - {name}: 参数 {params}")

        return True
    except Exception as e:
        print(f"❌ 工具系统测试失败: {e}")
        return False


def test_sse_protocol():
    """测试2: SSE协议事件生成"""
    print("\n" + "="*60)
    print("测试2: SSE协议事件生成")
    print("="*60)

    try:
        from src.contract_review.sse_protocol import (
            create_tool_thinking_event,
            create_tool_call_event,
            create_tool_result_event,
            create_doc_update_event,
            SSEEventType
        )

        # 测试各种事件
        events = {
            'tool_thinking': create_tool_thinking_event("测试思考"),
            'tool_call': create_tool_call_event('test_id', 'modify_paragraph', {'paragraph_id': 1}),
            'tool_result': create_tool_result_event('test_id', True, "成功", {}),
            'doc_update': create_doc_update_event('change_id', 'modify_paragraph', {})
        }

        for event_name, event_str in events.items():
            # 验证事件格式
            assert event_str.startswith('event:') or event_str.startswith('data:'), f"{event_name} 格式错误"
            print(f"  ✅ {event_name} 事件格式正确")

        return True
    except Exception as e:
        print(f"❌ SSE协议测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_llm_client_tools():
    """测试3: LLM客户端工具调用支持"""
    print("\n" + "="*60)
    print("测试3: LLM客户端工具调用支持")
    print("="*60)

    try:
        from src.contract_review.llm_client import LLMClient
        from src.contract_review.gemini_client import GeminiClient
        from src.contract_review.fallback_llm import FallbackLLMClient

        # 检查方法存在
        assert hasattr(LLMClient, 'chat_with_tools'), "LLMClient缺少chat_with_tools方法"
        assert hasattr(GeminiClient, 'chat_with_tools'), "GeminiClient缺少chat_with_tools方法"
        assert hasattr(FallbackLLMClient, 'chat_with_tools'), "FallbackLLMClient缺少chat_with_tools方法"

        print("  ✅ LLMClient.chat_with_tools 存在")
        print("  ✅ GeminiClient.chat_with_tools 存在")
        print("  ✅ FallbackLLMClient.chat_with_tools 存在")

        return True
    except Exception as e:
        print(f"❌ LLM客户端测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prompt_integration():
    """测试4: Prompt集成（文档结构注入）"""
    print("\n" + "="*60)
    print("测试4: Prompt集成")
    print("="*60)

    try:
        from src.contract_review.prompts_interactive import (
            build_item_chat_messages,
            format_document_structure
        )

        # 测试文档结构格式化
        test_paragraphs = [
            {"id": 1, "content": "第一段内容很长" * 10},
            {"id": 2, "content": "第二段"},
            {"id": 3, "content": "第三段"},
        ]

        doc_structure = format_document_structure(test_paragraphs, max_paragraphs=100)

        assert "[段落 1]" in doc_structure, "文档结构缺少段落1"
        assert "[段落 2]" in doc_structure, "文档结构缺少段落2"
        assert "[段落 3]" in doc_structure, "文档结构缺少段落3"

        print(f"  ✅ format_document_structure 工作正常")
        print(f"  文档结构示例:\n{doc_structure[:200]}...")

        # 测试消息构建
        messages = build_item_chat_messages(
            original_clause="原始条款",
            current_suggestion="当前建议",
            risk_description="风险描述",
            user_message="用户消息",
            chat_history=[],
            document_summary="",
            language="zh-CN"
        )

        assert len(messages) > 0, "消息列表为空"
        assert messages[0]['role'] == 'system', "第一条消息应为system"

        print(f"  ✅ build_item_chat_messages 工作正常，生成 {len(messages)} 条消息")

        return True
    except Exception as e:
        print(f"❌ Prompt集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_migration():
    """测试5: 数据库迁移验证"""
    print("\n" + "="*60)
    print("测试5: 数据库迁移验证")
    print("="*60)

    try:
        from src.contract_review.supabase_client import get_supabase_client

        supabase = get_supabase_client()

        # 尝试查询document_changes表（应该存在）
        response = supabase.table('document_changes').select('*').limit(1).execute()

        print(f"  ✅ document_changes表存在且可访问")
        print(f"  当前记录数: {len(response.data)}")

        return True
    except Exception as e:
        error_msg = str(e)
        if 'relation "document_changes" does not exist' in error_msg:
            print(f"  ❌ document_changes表不存在 - 需要执行migrations/003_document_changes.sql")
        else:
            print(f"  ❌ 数据库测试失败: {e}")
        return False


def print_summary(results):
    """打印测试总结"""
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)

    total = len(results)
    passed = sum(results.values())
    failed = total - passed

    print(f"\n总计: {total} 个测试")
    print(f"  ✅ 通过: {passed}")
    print(f"  ❌ 失败: {failed}")

    if failed > 0:
        print("\n失败的测试:")
        for test_name, result in results.items():
            if not result:
                print(f"  - {test_name}")

    return passed == total


def main():
    """主测试流程"""
    print("\n" + "="*60)
    print("AI工具调用功能 - 单元测试")
    print("="*60)

    results = {}

    # 执行各项测试
    results['工具系统'] = test_tool_system()
    results['SSE协议'] = test_sse_protocol()
    results['LLM客户端'] = test_llm_client_tools()
    results['Prompt集成'] = test_prompt_integration()
    results['数据库迁移'] = test_database_migration()

    # 打印总结
    all_passed = print_summary(results)

    if all_passed:
        print("\n🎉 所有测试通过！可以启动服务器进行端到端测试。")
        print("\n下一步:")
        print("  1. 启动后端: cd backend && python api_server.py")
        print("  2. 启动前端: cd frontend && npm run dev")
        print("  3. 在浏览器中测试完整流程")
    else:
        print("\n⚠️  部分测试失败，请先修复问题。")
        sys.exit(1)


if __name__ == '__main__':
    main()
