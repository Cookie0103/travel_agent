import type { components } from "./api-types";
export type MemoryFact = components["schemas"]["MemoryFactView"];
export const memoryLabels: Record<MemoryFact["key"], string> = {
  pace: "旅行节奏",
  wake_time: "平时起床时间",
  evening_end: "晚上结束时间",
  transport: "交通",
  lodging_type: "住宿类型",
  room_type: "房型",
  smoking: "禁烟",
  dietary: "饮食",
  interest: "兴趣",
  avoid: "希望避免",
  companion_pattern: "同行方式",
  budget_style: "预算风格",
};
const values: Record<string, string> = {
  慢节奏: "比较轻松",
  walk: "步行",
  transit: "公共交通",
  taxi: "出租车",
  hotel: "酒店",
  hostel: "青旅",
  ryokan: "日式旅馆",
  apartment: "公寓",
  private: "独立房间",
  dorm: "多人宿舍",
  capsule: "胶囊",
  any: "不限",
  nonsmoking: "禁烟",
  solo: "独自出行",
  couple: "两人出行",
  family: "家庭出行",
  friends: "朋友同行",
  economy: "节省",
  balanced: "均衡",
  premium: "舒适",
};
export function memoryValue(fact: MemoryFact) {
  return fact.value === null ? "已清除" : (values[fact.value] ?? fact.value);
}
export const memorySources: Record<MemoryFact["source"], string> = {
  user_utterance: "对话中逐条确认",
  manual: "手动填写",
  migrated: "原有偏好",
};
export const memoryStatuses: Record<MemoryFact["status"], string> = {
  proposed: "待确认",
  active: "生效",
  rejected: "未保存",
  superseded: "已被取代",
  deleted: "已删除",
};
