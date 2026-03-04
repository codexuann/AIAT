# app/main.py
"""
程序入口：
- 组装 Brain + SkillRuntime + SkillManager + 能力层（UI/视觉/声音）
- 接收用户输入：交给 Brain 决策 chat / skill + need_vision
- chat：直接用文字回答，或结合视觉回答
- skill：调用 SkillManager 创建并加载一个新的技能 Tab（并使用 LLM 生成技能代码）
"""

from config import UI_WINDOW_TITLE
from core.brain import Brain
from core.skill_runtime import SkillRuntime
from core.skill_manager import SkillManager
from capabilities import ui_adapter, vision_service, voice_service


def main():
    # 先创建 SkillManager（作为全局“技能 + 记忆”管理）
    skill_manager = SkillManager()

    # 再创建 Brain，并把 skill_manager 注入进去
    brain = Brain(skill_manager=skill_manager)

    # 运行时外壳：负责 UI / 摄像头守护 / 时间引擎 stub
    runtime = SkillRuntime(window_title=UI_WINDOW_TITLE)

    def on_user_input(text: str):
        """
        UI 输入入口：
        - Brain 决定：chat / skill + 是否需要视觉 need_vision
        - skill：交给 SkillManager 生成/加载新 skill（多 Tab 并存）
        - chat：
            - need_vision = true  → 基于摄像头画面 + 视觉模型回答
            - need_vision = false → 普通文字聊天（此时 skills JSON 已经注入到 Brain 的意图判断里）
        """
        ui_adapter.append_chat("You", text)

        route = brain.route_input(text)
        mode = route["mode"]
        reply = route["reply"]
        need_vision = route.get("need_vision", False)

        if mode == "skill":
            # 功能需求：生成/加载新 skill
            ui_adapter.append_chat("Assistant", reply)

            # 交给 SkillManager 统一处理技能创建 + 代码生成 + UI + 任务注册
            skill_manager.create_and_load_skill(text, brain)

        else:
            # 普通聊天
            if need_vision:
                # 基于视觉的聊天
                try:
                    vision_reply = vision_service.answer_with_vision(text)
                    final_reply = vision_reply
                except Exception as e:
                    # 摄像头/模型异常时的降级策略：用文字回答 + 简单说明
                    final_reply = f"视觉模块暂时不可用，我先根据文字简单说说：{reply}"
                    print("[main] vision chat error:", e)

                ui_adapter.append_chat("Assistant", final_reply)
                voice_service.speak_async(final_reply)
                # 视觉回答也记入对话历史
                brain.add_history("assistant", final_reply)

            else:
                # 纯文字聊天；skills JSON 已经在 Brain.route_input 里注入给 LLM 了
                ui_adapter.append_chat("Assistant", reply)
                voice_service.speak_async(reply)

    runtime.run(on_user_input)


if __name__ == "__main__":
    main()
