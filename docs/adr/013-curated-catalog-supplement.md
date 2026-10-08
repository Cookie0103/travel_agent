# ADR-013：公开来源补充数据独立版本与隔离评测

状态：接受；依据design/03数据来源与按失败例扩充、design/04 M3.6。不新增依赖或runtime。

原166条快照没有抹茶店铺，查询优化不能补出事实。新增显式选择的kyoto-matcha-v1包，保留真实OSM及英文Wikivoyage原响应、获取时间、SHA256和许可；中文攻略为标明版本的节选改写。未核对的店铺节点不算第二家店，冲突营业时间及当前价格保持未知，不给店名添加“抹茶”假别名。

复用load_snapshot、Place/Article及import_catalog。manifest可声明固定catalog.json；先校验两份原来源和整理文件哈希，再用现有领域schema验证非空、唯一ID。默认仍导入原快照；--snapshot-dir显式补充导入为upsert，不删除已有目录。

评测仅允许--catalog-dir配合--database的legacy dev实验；使用现有随机临时库，完整目录必须等于所选包，已有混合数据拒绝、不覆盖。实际data_version绑定所选manifest SHA，另保存目录SHA；冻结集、原fixture与历史结果不变。新数据结果不能与原目录成绩称作同版本改善。原kyoto-matcha案例只有search_content/search_places，回归保持此工具契约，不用新增详情工具替代。

备选：修改原快照会污染冻结基准；泛化抓取/翻译框架超出本次数据缺口；伪造别名或营业时间违反来源不变量。因此使用一个小补充包和原有入口。
