# =============================================================================
# 文件：src/tools/todo_write.py
# 作用："待办清单"工具。模型用它写下一份任务清单，并在干的过程中不断打勾。
#
# 为什么这东西有用？
#   模型干长任务时容易"忘事"——做到第三步就忘了用户的原始要求。
#   让它先列出 1、2、3、4，每完成一步就更新一次清单，
#   相当于给它自己一个"进度条"，也让你能看见它在干什么。
#
# 这个文件里真正的代码只有几十行，剩下 200 多行全是写给模型看的使用说明
# （那些 <example> 就是在教模型"什么情况该用、什么情况不该用"）。
#
# 【2026-11-06 第 3 轮】说明书和所有返回给模型的文字已改成中文。
# =============================================================================

import json  # json 库：把待办清单转成格式化的文字，方便模型读
from tools.base_tool import BaseTool  # 导入父类
from ui.ui_manager import UIManager  # 导入界面管理器，用来把清单漂亮地打印出来


class TodoWrite(BaseTool):
    is_repeatable = True  # 待办清单是会话级状态，重读不产生副作用，L3 压缩可安全折叠

    def __init__(self):
        super().__init__()  # 父类初始化
        self.todos = []  # 存当前的待办清单，一开始是空的
        self._ui_manager = UIManager()  # 界面管理器

    @staticmethod
    def get_tool_name():
        return "todo_write"  # 在模型眼里的名字

    async def act(self, todos=None):
        # todos 是一个列表，每一项长这样：
        #   {"content": "写一个函数", "status": "pending", "id": "1"}
        if not todos:  # 如果没传清单（空列表或 None）
            return "没有提供任何待办事项（todos 为空）。"

        # Validate todos type
        if not isinstance(todos, list):  # isinstance 用来检查"这是不是某种类型"
            # 模型有时会把 list 写成字符串，这里要拦住并告诉它错在哪
            return f"参数类型错误：todos 应该是列表，实际收到的是 {type(todos).__name__}。收到的内容：{todos}"

        for i, todo in enumerate(todos):  # 逐项检查
            if not isinstance(todo, dict):  # 每一项必须是字典
                return f"第 {i} 项的类型错误：每一项应该是对象，实际收到的是 {type(todo).__name__}。收到的内容：{todos}"

            required_fields = ['content', 'status', 'id']  # 三个必填字段
            for field in required_fields:  # 逐个检查有没有漏
                if field not in todo:  # 如果缺了某个字段
                    return f"第 {i} 项缺少必填字段 '{field}'。收到的内容：{todos}"

            if todo['status'] not in ['pending', 'in_progress', 'completed']:  # 状态只能是这三种
                return (f"第 {i} 项的状态 '{todo['status']}' 无效。"
                        f"只能是 pending（未开始）、in_progress（进行中）、completed（已完成）之一。收到的内容：{todos}")

        self.todos = todos  # 校验通过，用新清单整个替换旧的（注意：是整体替换，不是增量修改）

        # Display the updated todos using UI manager
        self._ui_manager.display_todos(todos)  # 在界面上把清单画出来

        return f"待办清单已更新，共 {len(todos)} 项。"  # 告诉模型"更新成功了"

    def json_schema(self):
        # 【2026-11-06 第 3 轮】参数说明改成中文（枚举值 pending/in_progress/completed 保持不变，
        # 因为它们是程序内部逻辑依赖的数据格式，改了就坏）
        return {
            "type": "function",
            "function": {
                "name": self.get_tool_name(),  # todo_write
                "description": self._tool_description(),  # 说明书（文件末尾那一大段）
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",  # 数组（列表）
                            "items": {  # items 描述"列表里每一项长什么样"
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "minLength": 1  # 内容至少 1 个字，不能是空的
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": [  # 只能是这三个值之一
                                            "pending",  # 待办（还没开始）
                                            "in_progress",  # 进行中（同一时间只该有一个）
                                            "completed"  # 已完成
                                        ]
                                    },
                                    "id": {
                                        "type": "string"  # 编号，用字符串形式（比如 "1"）
                                    }
                                },
                                "required": ["content", "status", "id"],  # 三项必填
                                "additionalProperties": False
                                # 不允许出现别的字段（防止模型乱加东西）
                            },
                            "description": "更新后的完整待办清单（注意是整体替换，不是增量修改）"
                        }
                    },
                    "required": ["todos"],
                    "additionalProperties": False
                }
            }
        }

    def get_status(self):
        # 这个方法会在每次工具执行完后被调用，用来生成"提醒模型看清单"的那段文字
        if not self.todos:  # 清单是空的
            return "当前没有任何待办事项，还没有添加过。"
        return json.dumps({"todos": self.todos}, indent=2, ensure_ascii=False)  # 转成带缩进的 JSON 文字，方便模型读
        # indent=2 表示每层缩进 2 个空格，纯粹为了好看
        # ensure_ascii=False 让中文原样输出，而不是变成 \u4e2d 这种转义码

    # adapt from claude code
    def _tool_description(self):
        # 【2026-11-18 压缩】从约 2400 token 压到约 200 token。
        #
        # 【为什么改】
        #   这段说明书原本是从 Claude Code 整段搬来的：8 个完整示例（4 个"该用"、
        #   4 个"不该用"），每个示例后面还跟一段 <reasoning> 说明"助手为什么这么判断"。
        #   实测它一个工具占掉 2522 token，是整个工具清单的 23%——
        #   比 file_read/file_write/file_edit/file_glob/file_grep 五个文件工具加起来还多。
        #   而这份清单每一轮请求都要整份发给模型，等于每一轮都按 2500 token 付费。
        #
        # 【为什么删示例是安全的】
        #   示例的作用是"教会不熟悉任务的模型什么时候该用"。现在的模型对
        #   "多步骤任务要列清单"这件事已经不需要示范；真正会影响行为的是
        #   **硬约束**（状态语义、只能一个 in_progress、什么情况下不许标 completed），
        #   这些全部保留在下面。删掉的只有：具体场景演示、reasoning 段落、
        #   以及三处重复表达同一条规则的句子。
        #
        # 【顺带修掉的畸形片段】
        #   原文第 202、207、227 行夹着 `</user>` `</assistant>` 这些孤立标签，
        #   是当初拷贝时串进来的，对模型是纯噪音。
        #
        # 【保留判断依据】
        #   "完成标准"那几条不是风格问题，是防止模型把没做完的活标成 completed：
        #   测试还在失败、只实现了一部分、有未解决的错误、缺依赖——四条全留。
        return """
为本次会话维护一份结构化待办清单，跟踪多步骤任务的进度。

什么时候用：
- 任务需要三步以上，或涉及多处改动
- 用户一次给了多项要求，或明确要清单
- 开始做某一项之前先标 in_progress，做完立刻标 completed

什么时候不用：
- 一步就能做完、纯问答，或跟踪它没有组织上的收益

状态：pending（未开始）/ in_progress（进行中）/ completed（已完成）。
任何时刻最多一个 in_progress；先完成当前项再开始下一项。

只有完全做完才能标 completed。测试仍在失败、只实现了一部分、还有未解决的错误、
缺必要依赖时，保持 in_progress，并新建一项描述"卡在哪"。

每一项都要具体可执行。每次提交的是**完整清单**：整体替换，不是增量修改。
        """.strip()
