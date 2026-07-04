const questions = [
  {
    key: "goal",
    text: "我们先不急着聊指标。你可以把这笔钱想成一个角色：它更像是要慢慢长大的长期资金，还是你希望它比普通理财更积极一点？",
    quick: ["长期慢慢增值", "比理财更积极", "希望追上大盘", "想抓行业机会"],
    ack: "明白，这会影响策略的底色：是先求稳，还是给增长留更多空间。"
  },
  {
    key: "comfort",
    text: "如果市场连续几周不太顺，你打开账户看到它在下跌，第一反应通常会是什么？这个问题没有标准答案，主要是帮我判断策略要不要更稳一点。",
    quick: ["会想先观望", "会想减少一点", "能接受波动", "可能想加一点"],
    ack: "好的，我会把这种心理感受放进安全边界里，而不是只看漂亮的收益曲线。"
  },
  {
    key: "lossRoom",
    text: "换成更具体的说法：如果投入 10 万元，短期最多少多少，你仍然可以冷静地继续执行计划？",
    quick: ["最多少8000", "少1万到1.5万", "少2万也能接受", "长期看能扛"],
    ack: "这个数字很有帮助。它会决定组合里防守类股票和进攻类股票的大致比例。"
  },
  {
    key: "attention",
    text: "你希望这套策略多省心？比如每周看一眼也可以，还是更希望一个月或一个季度再集中看一次？",
    quick: ["每周看一眼", "每月整理一次", "每季度调整", "尽量少操心"],
    ack: "收到。策略节奏要和你的生活节奏匹配，否则再好的模型也很难坚持。"
  },
  {
    key: "companyTaste",
    text: "说到选公司，你更容易信任哪一类？不用说专业名词，按直觉选就好。",
    quick: ["赚钱稳定", "现金分红多", "增长速度快", "行业前景好"],
    ack: "很好，这就是策略里最核心的选股偏好，我会把它转成可计算的筛选条件。"
  },
  {
    key: "avoid",
    text: "反过来，哪些股票会让你心里不踏实？比如公司连续亏损、行业你完全不了解、价格波动特别大，或者单一行业占太多。",
    quick: ["连续亏损公司", "看不懂的行业", "波动太大的股票", "不要押单一行业"],
    ack: "清楚了。先排除让你不舒服的部分，通常比一开始追求高收益更重要。"
  },
  {
    key: "experience",
    text: "你过去买过股票、基金或理财吗？我想知道你熟悉到什么程度，这样后面的解释可以刚刚好。",
    quick: ["刚开始了解", "买过基金", "买过股票", "有长期投资经验"],
    ack: "了解，我会按这个熟悉程度来展示结果，尽量让信息有用但不造成压力。"
  },
  {
    key: "constraint",
    text: "最后做一个执行边界确认：你更希望策略严格分散，还是允许少数看好的方向多放一点？",
    quick: ["严格分散", "单只别太重", "行业可稍集中", "保守一点"],
    ack: "好的，访谈信息已经比较完整了，我会把它整理成一份可检查、可回测的策略草案。"
  }
];

const yearOptions = {
  0: {
    years: 5,
    metrics: ["15.4%", "-13.8%", "较稳", "中等", "62%", "高"],
    strategy: [100, 108, 116, 111, 129, 146, 138, 161, 174, 189, 205],
    benchmark: [100, 105, 99, 112, 108, 118, 114, 124, 121, 131, 136],
    bars: [12, -6, 18, 9, 16]
  },
  1: {
    years: 10,
    metrics: ["13.1%", "-21.6%", "中上", "中等", "59%", "高"],
    strategy: [100, 96, 112, 124, 119, 138, 151, 146, 169, 188, 203, 226, 241],
    benchmark: [100, 94, 103, 112, 105, 118, 126, 117, 130, 139, 144, 151, 159],
    bars: [8, -12, 15, 6, 18, -4, 13, 11, 7, 14]
  },
  2: {
    years: 15,
    metrics: ["11.8%", "-27.4%", "中等", "偏低", "57%", "较高"],
    strategy: [100, 92, 106, 118, 111, 131, 145, 139, 163, 181, 173, 198, 223, 241, 265, 287],
    benchmark: [100, 88, 96, 108, 101, 115, 124, 112, 127, 135, 128, 141, 152, 158, 166, 174],
    bars: [5, -16, 13, 9, -3, 15, 7, 18, -8, 11, 10, 6, 16, 4, 12]
  }
};

const state = {
  index: 0,
  answers: {},
  refined: false,
  profileReady: false,
  backtestReady: false
};

const landingView = document.querySelector("#landingView");
const stage = document.querySelector("#stage");
const chatView = document.querySelector("#chatView");
const profileView = document.querySelector("#profileView");
const backtestView = document.querySelector("#backtestView");
const accountView = document.querySelector("#accountView");
const startButton = document.querySelector("#startButton");
const navStartButton = document.querySelector("#navStartButton");
const chatWindow = document.querySelector("#chatWindow");
const answerForm = document.querySelector("#answerForm");
const answerInput = document.querySelector("#answerInput");
const quickReplies = document.querySelector("#quickReplies");
const generateModelButton = document.querySelector("#generateModelButton");
const intentTitle = document.querySelector("#intentTitle");
const intentCopy = document.querySelector("#intentCopy");
const profileBadge = document.querySelector("#profileBadge");
const scoreList = document.querySelector("#scoreList");
const factorStack = document.querySelector("#factorStack");
const rulesBox = document.querySelector("#rulesBox");
const refineButton = document.querySelector("#refineButton");
const goBacktestButton = document.querySelector("#goBacktestButton");
const yearRange = document.querySelector("#yearRange");
const yearBadge = document.querySelector("#yearBadge");
const metrics = document.querySelector("#metrics");
const saveStrategyButton = document.querySelector("#saveStrategyButton");
const applyStrategyButton = document.querySelector("#applyStrategyButton");
const savedStrategyName = document.querySelector("#savedStrategyName");

const baseScores = {
  timeliness: 50,
  reliability: 50,
  expertise: 44,
  risk: 48,
  experience: 42
};

function showView(target) {
  [landingView, chatView, profileView, backtestView, accountView].forEach((view) => {
    view.classList.toggle("is-active", view === target);
  });
  const step =
    target === chatView
      ? "chat"
      : target === profileView
        ? "profile"
        : target === backtestView
          ? "backtest"
          : target === accountView
            ? "account"
            : "landing";
  stage.dataset.step = step;
}

function addMessage(kind, text) {
  const bubble = document.createElement("div");
  bubble.className = `message ${kind}`;
  bubble.textContent = text;
  chatWindow.appendChild(bubble);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function setQuickReplies(options) {
  quickReplies.innerHTML = "";
  options.forEach((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option;
    button.addEventListener("click", () => {
      if (state.index < questions.length) submitAnswer(option);
      else handlePostInterview(option);
    });
    quickReplies.appendChild(button);
  });
}

function askCurrentQuestion() {
  const current = questions[state.index];
  if (!current) {
    completeInterview();
    return;
  }
  addMessage("ai", current.text);
  setQuickReplies(current.quick);
}

function submitAnswer(value) {
  const answer = value.trim();
  if (!answer) return;
  const current = questions[state.index];
  state.answers[current.key] = answer;
  addMessage("user", answer);
  state.index += 1;
  answerInput.value = "";

  window.setTimeout(() => {
    if (current.ack) addMessage("ai", current.ack);
    if (state.index < questions.length) {
      window.setTimeout(() => askCurrentQuestion(), 260);
    } else {
      window.setTimeout(() => completeInterview(), 260);
    }
  }, 320);
}

function completeInterview() {
  addMessage(
    "ai",
    "信息已经足够了。我会先生成一版容易检查的策略草案。你可以确认结束对话，进入画像分析；也可以继续补充偏好。"
  );
  setQuickReplies(["确认结束对话", "想更稳一点", "想多一点增长", "少调整几次"]);
  renderStrategy();
  state.profileReady = true;
  refineButton.disabled = false;
  goBacktestButton.disabled = false;
  generateModelButton.hidden = false;
}

function deriveProfile() {
  const text = Object.values(state.answers).join(" ");
  const scores = { ...baseScores };

  if (/长期|慢慢|理财|观望|减少|最多少8000|1万到1.5万|分散|保守|现金分红|稳定|少操心/.test(text)) {
    scores.reliability += 24;
    scores.risk += 8;
  }
  if (/积极|大盘|行业机会|加一点|2万|长期看能扛|增长|前景|稍集中/.test(text)) {
    scores.timeliness += 22;
    scores.risk += 28;
  }
  if (/每周|每月/.test(text)) scores.timeliness += 16;
  if (/季度|尽量少操心|长期/.test(text)) scores.reliability += 12;
  if (/单只|行业|亏损|波动|分散|执行边界/.test(text)) scores.expertise += 18;
  if (/基金|股票|长期投资|大盘/.test(text)) scores.experience += 14;
  if (/刚开始/.test(text)) scores.experience -= 8;
  if (state.refined) {
    scores.reliability += 8;
    scores.expertise += 6;
  }

  Object.keys(scores).forEach((key) => {
    scores[key] = Math.max(18, Math.min(92, scores[key]));
  });
  return scores;
}

function deriveFactors() {
  const text = Object.values(state.answers).join(" ");
  if (/积极|行业机会|增长|前景|稍集中|加一点/.test(text)) {
    return [
      ["业绩增长", 28],
      ["近期走势", 24],
      ["质量稳定", 18],
      ["价格不过热", 16],
      ["波动较小", 14]
    ];
  }
  if (/分红|长期|慢慢|理财|稳定|观望|减少|保守|少操心/.test(text)) {
    return [
      ["股息率", 30],
      ["波动较小", 24],
      ["价格合理", 20],
      ["赚钱质量", 16],
      ["盈利稳定", 10]
    ];
  }
  return [
    ["价格合理", 26],
    ["赚钱质量", 22],
    ["盈利增长", 20],
    ["波动较小", 18],
    ["近期走势", 14]
  ];
}

function renderStrategy() {
  const scores = deriveProfile();
  const factors = deriveFactors();
  const answer = state.answers;
  const style = scores.risk >= 72 ? "进取增强型" : scores.risk >= 55 ? "均衡多因子型" : "稳健质量型";
  const goal = answer.goal || "长期慢慢增值";
  const rhythm = answer.attention || "每月整理一次";
  const preference = answer.companyTaste || answer.preference || "质量稳定";
  const guardrail = [answer.avoid, answer.constraint].filter(Boolean).join("，") || "分散配置";

  intentTitle.textContent = `${style} A 股策略`;
  savedStrategyName.textContent = `${style} A 股策略`;
  intentCopy.textContent = `目标：${goal}。节奏：${rhythm}。偏好：${preference}。边界：${guardrail}。`;
  profileBadge.textContent = scores.risk >= 72 ? "风险偏高" : scores.risk >= 55 ? "风险适中" : "偏稳健";

  scoreList.innerHTML = "";
  [
    ["时效性", scores.timeliness],
    ["可靠性", scores.reliability],
    ["专业性", scores.expertise],
    ["风险偏好", scores.risk],
    ["投资经验", scores.experience]
  ].forEach(([label, value]) => scoreList.appendChild(progressRow("score-row", label, value)));

  factorStack.innerHTML = "";
  factors.forEach(([label, value]) => factorStack.appendChild(progressRow("factor-row", label, value)));

  rulesBox.textContent = `股票池：A 股流动性较好的非 ST 股票；观察节奏：${rhythm}；安全边界：单股仓位不超过 10%，行业集中度不超过 35%，避开连续亏损与明显异常标的，并纳入交易成本、停牌与涨跌停约束。`;

  drawRadar(scores);
  drawBacktest(false);
}

function progressRow(className, label, value) {
  const row = document.createElement("div");
  row.className = className;
  row.innerHTML = `<span>${label}</span><div class="track"><div class="fill" style="width:${value}%"></div></div><strong>${value}</strong>`;
  return row;
}

function drawRadar(scores) {
  const canvas = document.querySelector("#radarChart");
  const ctx = canvas.getContext("2d");
  const labels = ["时效性", "可靠性", "专业性", "风险偏好", "投资经验"];
  const values = [scores.timeliness, scores.reliability, scores.expertise, scores.risk, scores.experience];
  const cx = canvas.width / 2;
  const cy = 155;
  const radius = 104;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#d7ddd2";
  ctx.fillStyle = "#050505";
  ctx.font = "13px Arial";

  for (let ring = 1; ring <= 4; ring += 1) {
    drawPolygon(ctx, cx, cy, radius * (ring / 4), labels.length);
    ctx.stroke();
  }

  labels.forEach((label, i) => {
    const angle = -Math.PI / 2 + (i * Math.PI * 2) / labels.length;
    const x = cx + Math.cos(angle) * (radius + 34);
    const y = cy + Math.sin(angle) * (radius + 26);
    ctx.textAlign = x < cx - 20 ? "right" : x > cx + 20 ? "left" : "center";
    ctx.fillText(label, x, y);
  });

  ctx.beginPath();
  values.forEach((value, i) => {
    const angle = -Math.PI / 2 + (i * Math.PI * 2) / values.length;
    const pointRadius = radius * (value / 100);
    const x = cx + Math.cos(angle) * pointRadius;
    const y = cy + Math.sin(angle) * pointRadius;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(223, 139, 97, 0.28)";
  ctx.strokeStyle = "#050505";
  ctx.lineWidth = 2;
  ctx.fill();
  ctx.stroke();
}

function drawPolygon(ctx, cx, cy, radius, sides) {
  ctx.beginPath();
  for (let i = 0; i < sides; i += 1) {
    const angle = -Math.PI / 2 + (i * Math.PI * 2) / sides;
    const x = cx + Math.cos(angle) * radius;
    const y = cy + Math.sin(angle) * radius;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

function updateMetrics(values) {
  const nodes = metrics.querySelectorAll("strong");
  values.forEach((value, index) => {
    nodes[index].textContent = value;
  });
}

function drawBacktest(active = true) {
  const option = yearOptions[yearRange.value];
  yearBadge.textContent = active ? `${option.years} 年数据` : "默认 5 年";
  updateMetrics(active ? option.metrics : ["--", "--", "--", "--", "--", "--"]);
  drawReturnChart(active ? option : null);
  drawBarChart(active ? option : null);
}

function drawReturnChart(option) {
  const canvas = document.querySelector("#returnChart");
  const ctx = canvas.getContext("2d");
  const strategy = option ? option.strategy : [100, 100, 100, 100, 100, 100];
  const benchmark = option ? option.benchmark : [100, 100, 100, 100, 100, 100];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawChartFrame(ctx, canvas.width, canvas.height, "累计增长");
  plotLine(ctx, strategy, "#050505", canvas.width, canvas.height);
  plotLine(ctx, benchmark, "#0a00b8", canvas.width, canvas.height);
  ctx.fillStyle = "#18211f";
  ctx.font = "13px Arial";
  ctx.fillText("策略", canvas.width - 102, 30);
  ctx.fillStyle = "#0a00b8";
  ctx.fillText("大盘参考", canvas.width - 62, 30);
}

function drawBarChart(option) {
  const canvas = document.querySelector("#barChart");
  const ctx = canvas.getContext("2d");
  const bars = option ? option.bars : [0, 0, 0, 0, 0];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawChartFrame(ctx, canvas.width, canvas.height, "每年表现");
  const max = 28;
  const chartLeft = 36;
  const chartBottom = canvas.height - 38;
  const slot = (canvas.width - 58) / bars.length;
  bars.forEach((value, i) => {
    const height = Math.abs(value / max) * 150;
    const x = chartLeft + i * slot + Math.max(2, slot * 0.14);
    const y = value >= 0 ? chartBottom - height : chartBottom;
    ctx.fillStyle = value >= 0 ? "#df8b61" : "#0a00b8";
    ctx.fillRect(x, y, Math.max(8, slot * 0.58), height || 2);
    if (bars.length <= 10 || i % 2 === 0) {
      ctx.fillStyle = "#050505";
      ctx.font = "12px Arial";
      ctx.textAlign = "center";
      ctx.fillText(`${i + 1}`, x + Math.max(8, slot * 0.58) / 2, canvas.height - 14);
    }
  });
}

function drawChartFrame(ctx, width, height, title) {
  ctx.strokeStyle = "#050505";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  ctx.fillStyle = "#050505";
  ctx.font = "14px Arial";
  ctx.textAlign = "left";
  ctx.fillText(title, 22, 28);
  ctx.strokeStyle = "#d4d4cf";
  for (let i = 1; i <= 4; i += 1) {
    const y = 42 + i * ((height - 82) / 4);
    ctx.beginPath();
    ctx.moveTo(34, y);
    ctx.lineTo(width - 22, y);
    ctx.stroke();
  }
}

function plotLine(ctx, values, color, width, height) {
  const max = Math.max(...values, 210);
  const min = Math.min(...values, 84);
  const left = 38;
  const top = 44;
  const chartWidth = width - 66;
  const chartHeight = height - 88;
  ctx.beginPath();
  values.forEach((value, i) => {
    const x = left + (i / (values.length - 1)) * chartWidth;
    const y = top + (1 - (value - min) / (max - min)) * chartHeight;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 3;
  ctx.stroke();
}

function handlePostInterview(value) {
  if (value === "确认结束对话") {
    showView(profileView);
    return;
  }

  state.refined = true;
  addMessage("user", value);
  if (value.includes("稳")) state.answers.constraint = `${state.answers.constraint || ""}，更稳一点`;
  if (value.includes("分红")) state.answers.preference = `${state.answers.preference || ""}，更看重分红`;
  if (value.includes("增长")) state.answers.preference = `${state.answers.preference || ""}，保留增长空间`;
  if (value.includes("少调整")) state.answers.attention = "每季度调整";
  window.setTimeout(() => {
    addMessage("ai", "已收到。我会把这条偏好写入策略边界，并重新生成画像与选股权重。");
    renderStrategy();
    generateModelButton.hidden = false;
  }, 260);
}

function startExperience() {
  landingView.classList.add("exit-up");
  window.setTimeout(() => {
    showView(chatView);
    answerInput.focus();
  }, 420);
}

startButton.addEventListener("click", startExperience);
navStartButton.addEventListener("click", startExperience);
generateModelButton.addEventListener("click", () => showView(profileView));

answerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.index < questions.length) submitAnswer(answerInput.value);
  else handlePostInterview(answerInput.value || "确认结束对话");
});

refineButton.addEventListener("click", () => {
  showView(chatView);
  addMessage("ai", "可以，我们只补充关键变化。你更想优先调整哪一点？更稳一点、多一点增长，还是少调整几次？");
  setQuickReplies(["确认结束对话", "更稳一点", "多一点增长", "少调整几次", "更看重分红"]);
});

goBacktestButton.addEventListener("click", () => {
  showView(backtestView);
  state.backtestReady = true;
  drawBacktest(true);
});

saveStrategyButton.addEventListener("click", () => {
  showView(accountView);
});

applyStrategyButton.addEventListener("click", () => {
  applyStrategyButton.textContent = "已加入模拟组合";
  applyStrategyButton.disabled = true;
});

yearRange.addEventListener("input", () => {
  drawBacktest(state.backtestReady);
});

addMessage("ai", "你好，我们先像聊天一样把投资习惯梳理清楚。你不用懂专业术语，按直觉回答就好；我会把这些信息整理成后面的策略草案。");
askCurrentQuestion();
renderStrategy();
