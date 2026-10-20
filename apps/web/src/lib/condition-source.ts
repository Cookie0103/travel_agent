/** Display only attribution returned by the server; absent sources stay unknown. */
const labels: Record<string, string> = {
  city: "目的地",
  hotel_search_location: "住宿查询地点",
  segments: "城市段",
  start_date: "开始日期",
  end_date: "结束日期",
  adults: "成人",
  child_ages: "儿童年龄",
  rooms: "房间数",
  budget: "全程预算",
  lodging_budget: "住宿预算",
  lodging_budget_unlimited: "每晚预算不限",
  transport: "交通",
  departure_time: "每日出发",
  soft_constraints: "节奏/偏好",
  interests: "兴趣",
  hard_constraints: "硬条件",
};

export function sourceLabel(
  sources: Readonly<Record<string, string>> | undefined,
  field: string,
): string {
  if (!sources || !Object.hasOwn(sources, field)) return "";
  return sources[field] === "conversation"
    ? "来自对话"
    : sources[field] === "user_form"
      ? "手动填写"
      : "";
}

export function sourceRows(
  sources: Readonly<Record<string, string>> | undefined,
): string[] {
  return Object.entries(labels).flatMap(([field, label]) => {
    const source = sourceLabel(sources, field);
    return source ? [`${label} · ${source}`] : [];
  });
}
