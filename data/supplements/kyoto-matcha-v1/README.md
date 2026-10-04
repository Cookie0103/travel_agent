# 京都抹茶开发补充快照 v1

此包单独显式使用，不能当作原fixture/166条快照/冻结评测的同版本数据。原始文件、UTC获取时间与SHA256见manifest.json；运行时不联网。

- osm.json：Overpass京都范围都路里/辻利的3个公开对象；保留原始响应。© OpenStreetMap contributors，[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)、[署名](https://www.openstreetmap.org/copyright)。
- wikivoyage.json：英文[Kyoto/Higashiyama固定5352679](https://en.wikivoyage.org/w/index.php?oldid=5352679)，© Wikivoyage contributors，[作者历史](https://en.wikivoyage.org/w/index.php?title=Kyoto/Higashiyama&action=history)、[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。全文原extract保留，不能标成中文原文。
- catalog.json：从OSM选择node/4775546783的实际店名/原别名/坐标/cafe类别；文章是上述英文条目的中文节选改写，删去历史价格/时段并增加未知及来源冲突说明、mentioned_places。衍生文章继续CC BY-SA 4.0，地点派生数据库遵守ODbL；不适用仓库代码许可。curation-v1 ID、来源版本及自身hash保留。

不把node/4444036291算作第二家店：位置紧邻但可能重复/对应不同楼层，未独立验证另一家甜品店。node/5273090896只有shop=gift，本包不推荐为cafe。店名不是“抹茶”的别名，不伪造别名；通过search_content查相关攻略、使用真实店名search_places。

[店铺官方页](https://www.giontsujiri.co.jp/store/saryotsujiri-honten/)本次显示的营业时段与OSM及旧Wiki文本不一致，结构化opening_hours保持null；indoor、当前价格和排队时长也未知。获取时间不是实时保证；原文里的历史金额不能用于结构化酒店报价或确定性预算。

导入：uv run --env-file .env python -m data.import_catalog --snapshot-dir data/supplements/kyoto-matcha-v1。
这是upsert补充，不删除原数据。评测必须使用独立临时库与明确catalog版本/hash；不得在已冻结原目录中静默加入。
