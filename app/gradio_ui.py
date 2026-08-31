import gradio as gr
import httpx

API_BASE = "http://localhost:4400"


async def chat_fn(question: str, datasource_id: int, history: list):
    if not question.strip():
        return history, ""

    payload = {
        "question": question,
        "agent_id": 1,
        "datasource_id": int(datasource_id) if datasource_id else None,
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{API_BASE}/api/chat", json=payload)
            data = resp.json()

        answer = data.get("answer", "无回答")
        sql = data.get("sql", "")
        intent = data.get("intent", "")

        display = f"**意图**: {intent}\n\n"
        if sql:
            display += f"**SQL**: `{sql}`\n\n"
        display += f"**结果**:\n{answer}"

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": display})
    except Exception as e:
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": f"请求失败: {e}"})

    return history, ""


def build_ui():
    with gr.Blocks(title="问渠 WenQu · 企业本体智能平台") as demo:
        gr.Markdown("# 问渠 WenQu 智能问数")
        gr.Markdown("输入自然语言问题，基于企业本体与查询语义自动返回结果。")

        with gr.Row():
            datasource_id = gr.Number(label="数据源ID", value=1, precision=0)

        chatbot = gr.Chatbot(label="对话", type="messages", height=500)
        with gr.Row():
            msg = gr.Textbox(label="输入问题", placeholder="例: 上个月的总销售额是多少？", scale=4)
            send_btn = gr.Button("发送", scale=1, variant="primary")

        msg.submit(chat_fn, [msg, datasource_id, chatbot], [chatbot, msg])
        send_btn.click(chat_fn, [msg, datasource_id, chatbot], [chatbot, msg])

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860)
