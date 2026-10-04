/** Chinese labels for backend tool names; unknown names are shown as received. */
const labels: Record<string, string> = {
  search_places: "搜索景点",
  search_content: "搜索攻略",
  get_article: "读取攻略",
  get_place_facts: "读取景点信息",
  search_hotel_offers: "比较酒店",
  refresh_hotel_offer: "刷新酒店报价",
  hold_hotel: "暂留酒店",
  estimate_routes: "估算路线",
  validate_itinerary: "校验行程",
  stage_plan_change: "生成行程草稿",
  update_travel_request: "更新旅行条件",
  get_weather_forecast: "查询天气",
  get_saved_plan: "读取已保存行程",
  present_travel_result: "整理结果卡片",
  load_skill: "载入技能",
};

export function toolLabel(name: string | null): string {
  if (!name) return "工具";
  const short = name.split("__").pop() ?? name;
  return labels[short] ?? name;
}
