import { useEffect, useRef, useState, type MouseEvent } from "react";
import { Bubble, Prompts, Sender, Welcome, type BubbleItemType } from "@ant-design/x";
import XMarkdown from "@ant-design/x-markdown";
import {
  DeleteOutlined,
  DislikeOutlined,
  LikeOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PaperClipOutlined,
  PlusOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Button, Card, Flex, Spin, Table, Tag, Typography, Upload } from "antd";
import type { ColumnsType } from "antd/es/table";
import "./App.css";

type Product = {
  id: number;
  name: string;
  category: string;
  brand: string | null;
  material: string | null;
  spec: string | null;
  model: string | null;
  size: string | null;
  length: string | null;
  process: string | null;
  origin: string | null;
  industry: string | null;
  price: number | null;
  unit: string;
  moq: number;
  lead_time: number;
  description: string | null;
  match_kind?: "exact" | "alternative";
  mismatches?: string[];
};

type ChatResponse = {
  reply: string;
  stage: string;
  items: Product[];
  rows?: ExcelRow[];
  summary?: string;
  options?: string[];
  message_id?: number;
  demand: { missing: string[] } | null;
};

type ExcelRow = {
  row_no: number;
  query: string;
  names: string[];
  items?: Product[];
  note: string;
  status?: string;
};

type ExcelResult = {
  file: string;
  summary: string;
  rows: ExcelRow[];
};

type Message = {
  role: "user" | "assistant";
  text: string;
  items?: Product[];
  rows?: ExcelRow[];
  summary?: string;
  excel?: ExcelResult;
  options?: string[];
  stage?: string;
  messageId?: number;
  rating?: "up" | "down";
};

type SessionMeta = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  count: number;
};

type StoredMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  rating?: "up" | "down" | null;
  payload?: {
    items?: Product[];
    rows?: ExcelRow[];
    summary?: string;
    excel?: ExcelResult;
    options?: string[];
    stage?: string;
  } | null;
};

const STORAGE_KEY = "shop-agent-session";
const COLLAPSE_KEY = "shop-agent-sidebar-collapsed";

const EXAMPLES = [
  "304 不锈钢 M8 螺丝，长度 30mm，1000 个",
  "我要买螺丝",
  "内径 20 的轴承要 50 个",
  "24V 开关电源 10 个",
];

function ProductCards({ items }: { items: Product[] }) {
  return (
    <div className="result-cards">
      {items.map((p) => (
        <Card key={p.id} size="small" variant="outlined">
          <Flex justify="space-between" align="center" wrap gap={8}>
            <Typography.Text strong>{p.name}</Typography.Text>
            <Typography.Text type="danger" strong>
              {p.price != null ? `¥${p.price}/${p.unit}` : "价格待询"}
            </Typography.Text>
          </Flex>
          <Flex gap={8} wrap align="center" style={{ marginTop: 6 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {[p.brand, p.category, p.material, p.model && p.model !== "-" ? p.model : null]
                .filter(Boolean)
                .join(" · ")}
            </Typography.Text>
            <Tag>MOQ {p.moq}</Tag>
            <Tag>交期 {p.lead_time} 天</Tag>
          </Flex>
          <Flex gap={6} wrap style={{ marginTop: 6 }}>
            {p.match_kind === "alternative" && (
              <Tag color="orange" title={(p.mismatches || []).join("；")}>
                替代品
              </Tag>
            )}
            {p.process && <Tag color="blue">工艺 {p.process}</Tag>}
            {p.origin && <Tag color="green">产地 {p.origin}</Tag>}
            {p.industry && <Tag color="purple">行业 {p.industry}</Tag>}
          </Flex>
          {p.description && (
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, margin: "6px 0 0" }}>
              {p.description}
            </Typography.Paragraph>
          )}
        </Card>
      ))}
    </div>
  );
}

// 校验文字太长会把右侧栏撑破，列表里只显示短标签，完整说明放 title
const STATUS_LABEL: Record<string, string> = {
  ok: "可下单",
  missing_param: "缺参数",
  missing_category: "缺品类",
  out_of_scope: "库外",
  no_match: "无匹配",
  alternative_only: "仅替代",
  attr_conflict: "属性不符",
  below_moq: "低于起订量",
};

function shortNote(note: string, status?: string): string {
  if (status && STATUS_LABEL[status]) return STATUS_LABEL[status];
  if (note === "可下单") return "可下单";
  if (note.startsWith("没看出")) return "缺品类";
  if (note.startsWith("参数不全") || note.startsWith("缺参数")) return "缺参数";
  if (note.startsWith("不在收录")) return "库外";
  if (note.startsWith("没有匹配")) return "无匹配";
  if (note.startsWith("无精确匹配")) return "仅替代";
  if (note.startsWith("信息不全")) return "缺参数";
  if (note.startsWith("产地")) return "产地不符";
  if (note.startsWith("材质")) return "材质不符";
  if (note.startsWith("工艺")) return "工艺不符";
  if (note.startsWith("适用行业")) return "行业不符";
  if (note.startsWith("品牌")) return "品牌不符";
  return note.slice(0, 8);
}

function ExcelTable({ data }: { data: ExcelResult }) {
  const columns: ColumnsType<ExcelRow> = [
    { title: "行", dataIndex: "row_no", width: 40 },
    {
      title: "清单",
      dataIndex: "query",
      width: 180,
      ellipsis: true,
      render: (q: string) => <span title={q}>{q}</span>,
    },
    {
      title: "推荐商品 / 校验",
      render: (_, row) => {
        const item = row.items?.[0];
        if (!item) {
          return (
            <Tag color="orange" title={row.note} style={{ marginInlineEnd: 0 }}>
              {shortNote(row.note, row.status)}
            </Tag>
          );
        }
        const attrs = [
          item.brand,
          item.spec,
          item.model && item.model !== "-" ? `型号 ${item.model}` : null,
          item.material,
          item.process,
          item.origin,
          item.industry,
        ].filter(Boolean) as string[];
        return (
          <Flex vertical gap={2}>
            <Typography.Text strong style={{ fontSize: 13 }}>
              {item.name}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: attrs.join(" · ") }}>
              {attrs.join(" · ")}
            </Typography.Text>
            <Flex gap={10} align="center" style={{ fontSize: 12 }}>
              <span style={{ color: "#cf1322" }}>
                ¥{item.price}/{item.unit}
              </span>
              <span style={{ color: "#8c8c8c" }}>MOQ {item.moq}</span>
              <span style={{ color: "#8c8c8c" }}>交期 {item.lead_time} 天</span>
              <Tag
                color={row.status === "ok" ? "green" : "orange"}
                title={row.note}
                style={{ marginInlineEnd: 0 }}
              >
                {shortNote(row.note, row.status)}
              </Tag>
            </Flex>
          </Flex>
        );
      },
    },
  ];

  return (
    <div style={{ marginTop: 10, width: "100%" }}>
      <Table
        size="small"
        rowKey="row_no"
        pagination={false}
        dataSource={data.rows}
        columns={columns}
      />
    </div>
  );
}

function OptionRow({
  options,
  onFill,
  disabled,
}: {
  options: string[];
  onFill: (value: string) => void;
  disabled?: boolean;
}) {
  const [picked, setPicked] = useState<string[]>([]);

  function toggle(option: string) {
    const next = picked.includes(option)
      ? picked.filter((o) => o !== option)
      : [...picked, option];
    setPicked(next);
    // 多选按英文逗号加空格拼接，填进输入框由用户确认后发送
    onFill(next.join(", "));
  }

  return (
    <Flex vertical gap={6} style={{ marginTop: 10 }}>
      <Flex gap={8} wrap>
        {options.map((o) => (
          <Button
            key={o}
            size="small"
            type={picked.includes(o) ? "primary" : "default"}
            disabled={disabled}
            onClick={() => toggle(o)}
          >
            {o}
          </Button>
        ))}
      </Flex>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {picked.length > 1
          ? `已选 ${picked.length} 项，已填入输入框，可以接着选`
          : "可以多选，选完在输入框里发送"}
      </Typography.Text>
    </Flex>
  );
}

function FeedbackRow({
  rating,
  onRate,
}: {
  rating?: "up" | "down";
  onRate: (r: "up" | "down") => void;
}) {
  return (
    <Flex gap={4} align="center" style={{ marginTop: 8 }}>
      <Button
        size="small"
        type={rating === "up" ? "primary" : "text"}
        icon={<LikeOutlined />}
        onClick={() => onRate("up")}
      />
      <Button
        size="small"
        type={rating === "down" ? "primary" : "text"}
        danger
        icon={<DislikeOutlined />}
        onClick={() => onRate("down")}
      />
      {rating && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {rating === "up" ? "收到，谢谢" : "记下了"}
        </Typography.Text>
      )}
    </Flex>
  );
}

// 右侧结果区：单需求显示商品卡，多需求显示表格，都没有时给占位
function ResultPanel({ message }: { message?: Message }) {
  if (!message) {
    return (
      <div className="result-empty">
        <Typography.Text type="secondary">
          推荐结果会固定显示在这一栏。说清需求或上传清单后，商品、报价和校验这里都能看到。
        </Typography.Text>
      </div>
    );
  }
  if (message.rows?.length) {
    return (
      <Flex vertical gap={8}>
        {message.summary && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {message.summary}
          </Typography.Text>
        )}
        <ExcelTable data={{ file: "", summary: message.summary ?? "", rows: message.rows }} />
      </Flex>
    );
  }
  if (message.items?.length) {
    return <ProductCards items={message.items} />;
  }
  if (message.excel) {
    return <ExcelTable data={message.excel} />;
  }
  return (
    <div className="result-empty">
      <Typography.Text type="secondary">这一轮没有商品结果。</Typography.Text>
    </div>
  );
}

function toMessages(list: StoredMessage[]): Message[] {
  return list.map((m) => ({
    role: m.role,
    text: m.text,
    items: m.payload?.items,
    rows: m.payload?.rows,
    summary: m.payload?.summary,
    excel: m.payload?.excel,
    options: m.payload?.options,
    stage: m.payload?.stage,
    messageId: m.id,
    rating: m.rating ?? undefined,
  }));
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // 流式请求的句柄：切换会话或发起新请求时用它中止旧流
  const abortRef = useRef<AbortController | null>(null);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [currentId, setCurrentId] = useState("");
  const [ready, setReady] = useState(false);
  // 历史会话栏可折叠，折叠状态存本地，刷新后保持
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === "1",
  );
  function toggleCollapsed() {
    setCollapsed((prev) => {
      localStorage.setItem(COLLAPSE_KEY, prev ? "0" : "1");
      return !prev;
    });
  }

  // 刷新页面后从后端恢复会话列表和最近一次打开的对话
  // StrictMode 下 effect 会跑两次，加个标记避免重复建会话
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void (async () => {
      try {
        const list: SessionMeta[] = await fetch("/api/sessions").then((r) => r.json());
        setSessions(list);
        const saved = localStorage.getItem(STORAGE_KEY);
        const target = list.find((s) => s.id === saved) ?? list[0];
        if (target) {
          await openSession(target.id, list);
        } else {
          await newSession();
        }
      } catch {
        // 后端没起来时先给个空会话，不阻断页面
        setReady(true);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function refreshSessions() {
    try {
      const list: SessionMeta[] = await fetch("/api/sessions").then((r) => r.json());
      setSessions(list);
    } catch {
      // 列表刷新失败不影响当前对话
    }
  }

  async function openSession(id: string, list?: SessionMeta[]) {
    abortRef.current?.abort();
    try {
      const data = await fetch(`/api/sessions/${id}`).then((r) => r.json());
      if (!data || !data.id) throw new Error("会话不存在");
      setCurrentId(id);
      localStorage.setItem(STORAGE_KEY, id);
      setMessages(toMessages(data.messages ?? []));
      if (list) setSessions(list);
    } catch {
      // 读不到就保持当前状态
    } finally {
      setReady(true);
    }
  }

  async function newSession() {
    abortRef.current?.abort();
    try {
      const s: SessionMeta = await fetch("/api/sessions", { method: "POST" }).then((r) => r.json());
      setCurrentId(s.id);
      localStorage.setItem(STORAGE_KEY, s.id);
      setMessages([]);
      setSessions((prev) => [s, ...prev]);
    } catch {
      // 新建失败时保持原状
    } finally {
      setReady(true);
    }
  }

  async function removeSession(id: string, event: MouseEvent) {
    event.stopPropagation();
    if (id === currentId) abortRef.current?.abort();
    try {
      await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    } catch {
      return;
    }
    const rest = sessions.filter((s) => s.id !== id);
    setSessions(rest);
    if (id === currentId) {
      if (rest.length) await openSession(rest[0].id, rest);
      else await newSession();
    }
  }

  async function send(text: string) {
    const q = text.trim();
    if (!q || loading || !currentId) return;
    setInput("");
    // 先放一条空的助手气泡，流式增量直接往这条里写，不再额外叠加 loading 气泡
    setMessages((m) => [...m, { role: "user", text: q }, { role: "assistant", text: "" }]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    const sessionId = currentId;

    const patchAssistant = (fn: (m: Message) => Message) => {
      // 旧请求（已中止或已被新请求顶掉）不能再改当前会话的最后一条助手消息
      if (controller.signal.aborted || abortRef.current !== controller) return;
      setMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].role === "assistant") {
            next[i] = fn(next[i]);
            break;
          }
        }
        return next;
      });
    };

    let gotResult = false;

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q, session_id: sessionId }),
        signal: controller.signal,
      });
      const contentType = res.headers.get("content-type") || "";
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      if (!res.body || !contentType.includes("text/event-stream")) {
        throw new Error(`响应不是事件流（content-type: ${contentType || "空"}）`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      const handle = (event: string, data: Record<string, unknown>) => {
        if (event === "delta") {
          const piece = String(data.text ?? "");
          if (piece) patchAssistant((m) => ({ ...m, text: m.text + piece }));
        } else if (event === "reset") {
          // 模型中途失败：清掉半截文本，等最终 result 换成模板内容
          patchAssistant((m) => ({ ...m, text: "" }));
        } else if (event === "result") {
          const r = data as unknown as ChatResponse;
          gotResult = true;
          patchAssistant(() => ({
            role: "assistant",
            text: r.reply,
            items: r.items,
            rows: r.rows,
            summary: r.summary,
            options: r.options,
            stage: r.stage,
            messageId: r.message_id,
          }));
        } else if (event === "error") {
          throw new Error(String(data.message ?? "流式请求失败"));
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // 一个 chunk 可能含多个事件、一个事件也可能跨 chunk，按空行切
        let idx = buffer.indexOf("\n\n");
        while (idx >= 0) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          let eventName = "";
          const dataLines: string[] = [];
          for (const line of raw.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (eventName && dataLines.length) {
            handle(eventName, JSON.parse(dataLines.join("\n")));
          }
          idx = buffer.indexOf("\n\n");
        }
      }
      // 流结束了却没收到 result：网络中断或服务端提前关闭，不能当成成功
      if (!gotResult) {
        throw new Error("回复中断，没有收到完整结果");
      }
      void refreshSessions();
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      // 已有半截文本时追加说明，不能因为 m.text 非空就把失败藏掉
      patchAssistant((m) => ({
        ...m,
        text: m.text ? `${m.text}\n\n> 回复中断：${String(e)}` : `请求失败：${String(e)}`,
      }));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setLoading(false);
    }
  }

  // 点赞/点踩：先更新界面再发请求，失败只打日志，不打扰用户
  function rate(index: number, messageId: number, rating: "up" | "down") {
    setMessages((prev) =>
      prev.map((m, i) => (i === index ? { ...m, rating } : m)),
    );
    void fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId, rating }),
    }).catch((e) => console.error("反馈提交失败", e));
  }

  // 上传采购清单或商品截图：后端逐行识别并匹配，前端只负责把结果表格渲染出来
  async function upload(file: File) {
    if (loading || !currentId) return;
    const isImage = /\.(png|jpe?g|webp|gif|bmp)$/i.test(file.name);
    setMessages((m) => [...m, { role: "user", text: `上传了 ${file.name}` }]);
    setLoading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("session_id", currentId);
    try {
      const res = await fetch("/api/chat/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      const verb = isImage ? "识别完成" : "解析完成";
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: `**${data.file}** ${verb}，${data.summary}`,
          excel: data,
          messageId: data.message_id,
        },
      ]);
      void refreshSessions();
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `上传失败：${String(e)}` }]);
    } finally {
      setLoading(false);
    }
  }

  const bubbleItems: BubbleItemType[] = messages.map((m, i) => ({
    key: i,
    role: m.role,
    content: m.text,
    footer: (
      <Flex vertical gap={4} style={{ width: "100%" }}>
        {m.options?.length ? (
          <OptionRow options={m.options} onFill={(v) => setInput(v)} disabled={loading} />
        ) : null}
        {m.role === "assistant" && m.items?.length ? (
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 6 }}>
            找到 {m.items.length} 个候选，明细在右侧
          </Typography.Text>
        ) : null}
        {m.role === "assistant" && m.rows?.length ? (
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 6 }}>
            {m.rows.length} 条需求，按行核对在右侧
          </Typography.Text>
        ) : null}
        {m.role === "assistant" && m.messageId ? (
          <FeedbackRow rating={m.rating} onRate={(r) => rate(i, m.messageId!, r)} />
        ) : null}
      </Flex>
    ),
  }));

  // 流式期间不再叠加全局 loading 气泡：send() 已经建好了实际助手气泡，
  // 进度和正文都写在那一条里，避免出现两个"正在输入"的泡泡。

  // 结果区固定显示最近一条带商品的消息，切换会话时自然跟着走
  const lastResult = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && (m.items?.length || m.rows?.length || m.excel));

  const sender = (
    <Sender
      value={input}
      onChange={(v) => setInput(v)}
      onSubmit={(v) => send(v)}
      loading={loading}
      placeholder="描述你需要的工业品，例如：内径 20 的轴承要 50 个"
      prefix={
        <Upload
          accept=".xlsx,.xlsm,.png,.jpg,.jpeg,.webp,.gif,.bmp"
          showUploadList={false}
          beforeUpload={(file) => {
            void upload(file as File);
            return false;
          }}
        >
          <Button type="text" icon={<PaperClipOutlined />} title="上传采购清单（xlsx）或商品截图" />
        </Upload>
      }
    />
  );

  // 没开始对话时先给整页欢迎页，说过话以后（或点开历史会话）再分出右侧结果区
  const started = messages.length > 0;

  return (
    <div className="app">
      <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="sidebar-head">
          {!collapsed && <span className="brand">工业品导购</span>}
          <Button
            size="small"
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={toggleCollapsed}
            title={collapsed ? "展开历史会话" : "收起历史会话"}
          />
          {!collapsed && (
            <Button
              size="small"
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => newSession()}
              disabled={!ready}
            >
              新对话
            </Button>
          )}
        </div>
        {collapsed ? (
          <div className="session-list collapsed">
            <Button
              type="primary"
              shape="circle"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => newSession()}
              disabled={!ready}
              title="新对话"
            />
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`session-item${s.id === currentId ? " active" : ""}`}
                onClick={() => openSession(s.id)}
                title={s.title}
              >
                <span className="session-initial">{s.title.slice(0, 1)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="session-list">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`session-item${s.id === currentId ? " active" : ""}`}
                onClick={() => openSession(s.id)}
                title={s.title}
              >
                <span className="session-title">{s.title}</span>
                <DeleteOutlined className="session-del" onClick={(e) => removeSession(s.id, e)} />
              </div>
            ))}
          </div>
        )}
      </aside>

      <div className="main">
        <header className="header">
          <h1>工业品导购 Agent</h1>
          <p>用自然语言描述需求，直接给出可下单的商品清单</p>
        </header>

        {!ready ? (
          <Flex align="center" justify="center" style={{ flex: 1 }}>
            <Spin />
          </Flex>
        ) : started ? (
          <div className="workspace">
            <section className="chat-col">
              <main className="chat">
                <Bubble.List
                  items={bubbleItems}
                  autoScroll
                  style={{ height: "100%" }}
                  role={{
                    user: { placement: "end", variant: "filled", shape: "corner" },
                    assistant: {
                      placement: "start",
                      variant: "outlined",
                      shape: "corner",
                      contentRender: (content) => (
                        <XMarkdown content={String(content)} className="md" openLinksInNewTab />
                      ),
                    },
                  }}
                />
              </main>
              <footer className="footer">{sender}</footer>
            </section>
            <aside className="result-col">
              <div className="result-head">
                <span>商品结果</span>
              </div>
              <div className="result-body">
                <ResultPanel message={lastResult} />
              </div>
            </aside>
          </div>
        ) : (
          <>
            <main className="chat welcome">
              <Flex vertical gap={28} style={{ paddingTop: 40 }}>
                <Welcome
                  variant="borderless"
                  icon={<RobotOutlined style={{ fontSize: 40, color: "#2563eb" }} />}
                  title="说说你要采购什么"
                  description="说出品类、规格和数量，我帮你找可下单的商品，并提示 MOQ 和交期。"
                />
                <Prompts
                  title="试试这些"
                  wrap
                  items={EXAMPLES.map((e, i) => ({ key: String(i), label: e }))}
                  onItemClick={({ data }) => send(String(data.label))}
                />
              </Flex>
            </main>
            <footer className="footer">{sender}</footer>
          </>
        )}
      </div>
    </div>
  );
}
