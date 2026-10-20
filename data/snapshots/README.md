# 京都公开快照及署名

获取于2026-10-03；精确UTC时间、原始请求和SHA256见manifest.json。导入时校验原始文件，不联网。

- wikivoyage.json：中文Wikivoyage「京都」文本extract，版本196315（2024-02-28）。© Wikivoyage contributors。
  [固定版本](https://zh.wikivoyage.org/w/index.php?oldid=196315)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=京都&action=history)、[许可CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。
  导入改动：按标题切段、去空段、生成稳定ID；原文不改写。文本及衍生段落继续使用CC BY-SA 4.0，不适用仓库代码许可。
- osm.json：京都范围博物馆及部分主要景点，经Overpass导出，数据基准为2026-06-01T08:52:28Z（早于抓取时间）。© OpenStreetMap contributors。
  [署名说明](https://www.openstreetmap.org/copyright)、[数据库许可ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)。
  导入改动：字段选择/名称别名整理，node保留坐标、way/relation保留包围盒中心并标类型；派生数据库保持ODbL，不适用仓库代码许可。

来源有错漏和历史信息：获取时间不等于内容更新时间；不能当实时营业/交通/价格保证。文章里的票价和路线不用于结构化报价或确定性路线校验。
146个OSM对象可能包含同一场所的节点和区域，保留各自OSM ID，不擅自合并同名地点。城市是本次京都范围筛选，非推断每条OSM都有city标签。
缺少indoor/opening_hours保持null；不按“博物馆”猜成纯室内。营业时间只支持小子集，季节/公共假日等复杂规则返回unknown。
搜索暂用已有名称/别名子串，不为提高评测分伪造中文别名或源数据。
