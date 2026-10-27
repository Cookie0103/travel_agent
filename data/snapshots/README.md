# 公开快照及署名

京都两份文件获取于2026-10-03，其他城市攻略获取于2026-10-27；精确UTC时间、原始请求和SHA256见manifest.json。导入时校验原始文件，不联网。

- wikivoyage.json：中文Wikivoyage「京都」文本extract，版本196315（2024-02-28）。© Wikivoyage contributors。
  [固定版本](https://zh.wikivoyage.org/w/index.php?oldid=196315)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=京都&action=history)、[许可CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。
  导入改动：按标题切段、去空段、生成稳定ID；原文不改写。文本及衍生段落继续使用CC BY-SA 4.0，不适用仓库代码许可。
- wikivoyage-<城市>.json：另13个日本城市的中文Wikivoyage条目，请求方式与京都相同（同一extract+revision API、相同JSON结构）。© Wikivoyage contributors，许可、导入改动同上；每段攻略来源固定到该页oldid。
  - wikivoyage-tokyo.json：「東京」版本209270（2025-09-14），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=209270)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E6%9D%B1%E4%BA%AC&action=history)。
  - wikivoyage-osaka.json：「大阪」版本224411（2026-10-19），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=224411)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E5%A4%A7%E9%98%AA&action=history)。
  - wikivoyage-nara.json：「奈良」版本224419（2026-10-19），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=224419)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E5%A5%88%E8%89%AF&action=history)。
  - wikivoyage-kobe.json：「神戶」版本194971（2023-10-30），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=194971)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E7%A5%9E%E6%88%B6&action=history)。
  - wikivoyage-sapporo.json：「札幌」版本145776（2019-10-18），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=145776)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E6%9C%AD%E5%B9%8C&action=history)。
  - wikivoyage-nagoya.json：「名古屋」版本193128（2023-07-22），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=193128)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E5%90%8D%E5%8F%A4%E5%B1%8B&action=history)。
  - wikivoyage-kanazawa.json：「金泽」版本212168（2025-11-11），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=212168)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E9%87%91%E6%B3%BD&action=history)。
  - wikivoyage-hakone.json：「箱根」版本224618（2026-10-19），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=224618)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E7%AE%B1%E6%A0%B9&action=history)。
  - wikivoyage-kamakura.json：「镰仓」版本134065（2019-06-13），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=134065)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E9%95%B0%E4%BB%93&action=history)。
  - wikivoyage-hiroshima.json：「廣島」版本224462（2026-10-19），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=224462)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E5%BB%A3%E5%B3%B6&action=history)。
  - wikivoyage-fukuoka.json：「福岡」版本223926（2026-10-10），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=223926)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E7%A6%8F%E5%B2%A1&action=history)。
  - wikivoyage-nagasaki.json：「長崎」版本153386（2020-01-25），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=153386)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E9%95%B7%E5%B4%8E&action=history)。
  - wikivoyage-naha.json：「那霸」版本224719（2026-10-19），[固定版本](https://zh.wikivoyage.org/w/index.php?oldid=224719)、[作者历史](https://zh.wikivoyage.org/w/index.php?title=%E9%82%A3%E9%9C%B8&action=history)。
  - 城市字段和标题前缀用条目原标题（站内繁简混用，如東京/廣島/镰仓），不做繁简转换；检索的简体/英文写法只经`CITY_ALIASES`有限别名。
  - 函馆/函館、仙台在zh.wikivoyage没有条目（2026-10-27查询），未收录，也不用其他城市或语言版本代替。
- osm.json：京都范围博物馆及部分主要景点，经Overpass导出，数据基准为2026-06-01T08:52:28Z（早于抓取时间）。© OpenStreetMap contributors。
  [署名说明](https://www.openstreetmap.org/copyright)、[数据库许可ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)。
  导入改动：字段选择/名称别名整理，node保留坐标、way/relation保留包围盒中心并标类型；派生数据库保持ODbL，不适用仓库代码许可。

来源有错漏和历史信息：获取时间不等于内容更新时间；不能当实时营业/交通/价格保证。文章里的票价和路线不用于结构化报价或确定性路线校验。
146个OSM对象可能包含同一场所的节点和区域，保留各自OSM ID，不擅自合并同名地点。城市是本次京都范围筛选，非推断每条OSM都有city标签。
缺少indoor/opening_hours保持null；不按“博物馆”猜成纯室内。营业时间只支持小子集，季节/公共假日等复杂规则返回unknown。
搜索暂用已有名称/别名子串，不为提高评测分伪造中文别名或源数据。
