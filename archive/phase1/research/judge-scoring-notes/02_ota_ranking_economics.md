# OTA 与酒店 metasearch 的排序经济学、预订决策因素与付费排序边界（调研笔记 02）

> 调研日期：2026-11-26。每条数字都标注年份与来源类型：【审计/官方】=年报、监管文件、平台自己的对外说明；【监管】=监管机构文件；【学术】=论文；【厂商营销】=平台或供应商自述的效果数字；【媒体/博客】=媒体报道、第三方指南；【检索摘要】=我只看到搜索引擎对该页面的摘录，原页抓取失败（403/429），引用前建议再核对原文。标注"自算"的数字是我用已引用的原始数字做的除法，不是来源直接给出的。

## 1. 收入模型：各平台佣金率、付费可见度项目、阶梯返佣、take rate

### Takeaway
酒店 OTA 的整体 take rate（收入/交易额）在 12%–14% 左右（Booking Holdings 2024 年 14.3%，Expedia Group 2024 年约 12.3%），单店基础佣金按市场在 8%–15% 之间，付费可见度项目普遍是"在基础佣金上再加若干个百分点换排序"，其中 Preferred 类常驻项目约 +2~3 个百分点，临时加价类没有公开上限。除携程（因 2026 年反垄断处罚而被详细披露）外，中国和日本平台的费率只有媒体与第三方博客口径，没有官方费率表。

### Cited Findings

**整体 take rate（审计口径）**
- 【审计/官方，2024】Booking Holdings：gross bookings 1,655.80 亿美元（2023 年 1,506.27 亿），total revenues 237.39 亿美元；年报直接给出"revenues as a percentage of gross bookings"为 14.3%（2023 年 14.2%）。merchant gross bookings 1,041.82 亿 / merchant revenues 141.42 亿；agency gross bookings 613.98 亿 / agency revenues 85.24 亿；advertising and other revenues 10.73 亿；room nights 11.44 亿；marketing expenses 72.78 亿美元，占 gross bookings 4.4%；alternative accommodations 约占 Booking.com room nights 的 35%；直接流量占 room nights 的 mid-fifties percent；2024 年取消率"与 2023 年持平"，但未披露具体百分比 — [Booking Holdings FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000010/bkng-20241231.htm)
- 【审计/官方，2024，检索摘要】Expedia Group：revenue 136.91 亿美元，gross bookings 1,109.21 亿美元；按产品 Lodging 109.50 亿、Advertising and media 9.54 亿、Air 4.28 亿、Other 13.59 亿；B2C 92.74 亿、B2B 41.02 亿、trivago 第三方收入 3.15 亿；booked room nights 3.839 亿 — [Expedia Group FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1324424/000132442425000008/expe-20241231.htm)；[Q4 2024 earnings release](https://www.sec.gov/Archives/edgar/data/0001324424/000132442425000005/earningsrelease-q42024.htm)
- 【审计/官方，2024】Trip.com Group：accommodation reservation 收入 216 亿元人民币（+25%），transportation ticketing 203 亿元（+10%），packaged tours 43 亿元（+38%），total revenues 534 亿元（+20%）。年报摘录里没有给出酒店 GMV，因此算不出官方 take rate — [Trip.com Group FY2024 Form 20-F](https://www.sec.gov/Archives/edgar/data/1269238/000119312525078429/d779353d20f.htm)
- 【审计/官方，2024】trivago（metasearch）：按 CPC 向广告主收费，"each advertiser determines the amount it wants to pay per referral by bidding"；2024 年 total revenue 4.608 亿欧元，Referral Revenue 4.562 亿欧元，ROAS 132.1%（2023 年 147.6%）— [trivago FY2024 Form 20-F](https://www.sec.gov/Archives/edgar/data/1683825/000168382525000013/trvg-20241231.htm)

**Booking.com 的佣金与可见度项目**
- 【官方，页面注明日期 2025-05-31】Booking.com 对消费者的说明：默认排序叫"Our top picks"；排名靠前需要在点击量、总预订量、扣除取消后的预订量三方面都表现好；"how much commission they pay us on bookings"、"how quickly they usually pay it"、是否加入 Genius 或 Preferred Partner (+) Programme 也会影响排序；带 thumbs-up 徽章的住宿"pay us a higher commission if you make a booking"；带"Ad"徽章表示服务方付费出现在该位置。该页提示新版 How We Work 于 2026-12-10 生效 — [Booking.com How we work](https://www.booking.com/content/how_we_work.en-gb.html)
- 【官方，检索摘要】Preferred Partner Programme 面向表现最好的约 30% 合作方；资格为 performance score ≥70%、review score ≥7、对外价格"competitive"，每 90 天复核；代价是"a small commission increase"，换取搜索可见度和 thumbs-up 标识 — [Booking.com Partner Help: Preferred Partner Programme](https://partner.booking.com/en-gb/help/growing-your-business/increase-revenue/all-you-need-know-about-preferred-partner-programme)
- 【官方，检索摘要】Preferred Plus 面向 Preferred 合作方中的前 10%，以额外佣金换取"up to 60% increased visibility" — [Booking.com Partner Help: Preferred Plus](https://partner.booking.com/en-us/help/growing-your-business/increase-revenue/all-you-need-know-about-preferred-plus)
- 【官方，检索摘要】Visibility Booster 是短期工具：酒店自己为指定日期设定更高佣金，后台会预估浏览量增幅；用途包括提升特定日期排名、转卖被取消的房间 — [Booking.com Partner Help: Visibility Booster](https://partner.booking.com/en-us/help/growing-your-business/increase-revenue/all-you-need-know-about-visibility-booster)
- 【官方，检索摘要】若某笔订单佣金高于合同费率，原因可能是参加了 Genius、Preferred Partner 或 Visibility Booster — [Booking.com Partner Help: Understanding our commission](https://partner.booking.com/en-us/help/commission-invoices-tax/commission/understanding-our-commission)
- 【监管，数据采于 2020 年秋】丹麦竞争与消费者管理局（DCCA）研究"一家大型 OTA"时记录：常驻型排名提升（permanent ranking boost）当时的标价是佣金 +3 个百分点 — [DCCA 2023, Do ranking boosts harm consumers and competition?](https://kfst.dk/media/v0snxsvj/ranking-boosts.pdf)
- 【媒体/博客，2025–2026】多家第三方房东指南的口径：基础佣金约 15%（按市场 10%–25%）；Preferred 约 +2~3 个百分点（合计约 18%），自述效果"+65% page views、+40% bookings"；Preferred Plus 合计约 23%；Visibility Booster 叠加后总费率可超过 25%。这些不是 Booking.com 官方费率表，各指南数字互有出入 — [holidayfox 2026](https://www.holidayfox.com/en/partners/guides/cost-guides/booking-com-commission-breakdown-2026)；[Little Hotelier](https://www.littlehotelier.com/blog/get-more-bookings/preferred-partner-program)；[mara-solutions](https://www.mara-solutions.com/post/booking-com-visibility-booster-is-it-worth-the-investment-for-hotels-and-property-owners)

**Expedia 的 Accelerator 与 TravelAds**
- 【官方，检索摘要】Expedia 的排序说明：住宿排序会计入"compensation on bookings including compensation from our partner program Accelerator"；优先级表述为"Offer Strength, Quality Score, and compensation"；佣金是"properties with similar offers"之间决定相对顺序的因素之一；在 Vrbo 等度假租赁站点佣金不参与排序 — [Expedia sort order info](https://www.expedia.com/lp/b/sort-order-info)
- 【官方 + 厂商营销，2025】Accelerator 是 pay-per-stay：酒店自设额外 compensation 比例，仅在客人完成入住后支付，上线前可预览对 sort order 的影响，提升的是自然排序位置；TravelAds Sponsored Listings 是 pay-per-click 的赞助位。Expedia 自述使用 Accelerator 的酒店 gross booking value 高 20%、net room nights 多 20%（未给基线和方法）— [Expedia Group Partner blog](https://partner.expediagroup.com/en-us/resources/blog/travelads-and-accelerator-hotel-visibility-boosters)
- 【媒体，2016】Accelerator 上线时的行业报道：参与酒店支付的佣金最高可达 Expedia 通常 15% 佣金的两倍；美国酒店业协会 AHLA 批评其抬高分销成本且排序不透明。这是上线期数字，现行条款未核实 — [Travel Weekly 2016](https://www.travelweekly.com/Travel-News/Hotel-News/Expedia-pay-for-positioning-program-riles-hotel-trade-group)；[Skift 2016](https://skift.com/2016/03/03/first-look-at-expedias-hotel-accelerator-program-for-improving-hotel-placement/)

**Agoda**
- 【官方，检索摘要】Agoda Growth Program（AGP）分 Basic 10% / Standard 12% / Premium 15% 三档"cost per booking"，包含搜索排名提升和更多 metasearch/PPC 投放；Sponsored Listing 是 Agoda 唯一保证搜索结果页位置的产品，按"incremental commission, or cost per booking"计费，金额随地点和需求浮动，不提供固定费率 — [Agoda Partner Hub: AGP](https://partnerhub.agoda.com/zh-cn/?p=96660)；[Agoda Partner Hub: Sponsored Listing](https://www.partnerhub.agoda.com/zh-tw/?p=95369)；[Agoda Connect: Growth Program](https://connect.agoda.com/programs/growth-program.html)

**日本：楽天トラベル、じゃらん**
- 【媒体/博客，2025-06】住宿业服务商整理的费率表：じゃらんnet 1 名利用 6%、2 名以上 8%；楽天トラベル 1 名利用 7%、2 名以上 8.25% — [宿楽 2025-06 OTA手数料保存版](https://www.yadoraku.co.jp/news/news-733/)
- 【媒体/博客，2026】另一批文章的口径：じゃらんnet 2 名以上 10.0%（基本 8.0% + ポイント原資 2.0%）；楽天トラベル 2 名以上 9.25%；Booking.com 与 Agoda 在日本为 12.0%；一休.com 与 Yahoo!トラベル 为 10.0%；另有事前決済 +2%、ポイント原資 1–2%、クーポン約 3% 等附加成本。两批来源的数字不一致，可能是统计口径（是否含积分原资）或调价所致 — [トラベルコネクト 2026-10](https://travel-connect.jp/ota-commission-guide/)；[Tip 2026-08](https://tip-biz.co.jp/media/ota-commission-direct-booking-2026/)；[dot-homes 2026](https://dot-homes.jp/column/ota-fee/)
- 【媒体，2005】历史参照：楽天トラベル把一律 6% 的システム利用料改为按利用形态 7–9%，送客量和站内曝光越多费率越高 — [ITmedia 2005](https://www.itmedia.co.jp/news/article/0508/30/1050830002/)

**中国：携程、美团、飞猪**
- 【媒体，2025–2026】携程酒店分层：无牌约 10%、金牌约 12%、特牌约 15%；展示顺序特牌 > 金牌 > 无牌；金牌要求携程价格比其他平台低约 5%，特牌要求线上独家；叠加推广工具后实际综合抽佣最高可达 30% — [腾讯新闻 2025-09](https://news.qq.com/rain/a/20250919A07VQ500)；[中新经纬 2026-05](https://www.jwview.com/jingwei/html/m/05-16/670889.shtml)；[新浪财经 2026-01](https://finance.sina.cn/2026-01-15/detail-inhhkmpx6430567.d.html?vt=4)
- 【监管，2026-07-25】市场监管总局对携程罚没合计 51.79 亿元（没收违法所得 16.58 亿元 + 罚款 35.21 亿元），并责令退还强制扣除的订单储备金 1.22 亿元；认定携程 2020 年以来"以流量分配机制为核心"，要求"特牌"酒店独家合作、强制"金牌""无牌"酒店给予"全网最低价"，并以限流、"摘牌"等方式保障执行；携程市场份额连续多年接近或超过 50% — [新华网 2026-07-25](https://www.news.cn/fortune/20260725/cbf7170e42de4b0f8e81e83dd41a2709/c.html)
- 【媒体，2024】抖音住宿佣金自 2024-07-01 起由 4.5% 上调至 8.0%（UBS 报告口径）— [Futu News 转引 UBS](https://news.futunn.com/en/post/45455480/the-big-bank-ubs-group-meituan-03690-hk-core-business)
- 【媒体，未标注原始出处】"各平台默认佣金 8%–15%"；"行业平均佣金率 10%–12%"。两个说法都没有可追溯的原始数据 — [脉脉：酒店OTA排名规则](https://maimai.cn/article/detail?fid=856851980&efid=VP10LfGI-Xfh2S4RJEqVYg)；[界面新闻](https://www.jiemian.com/article/12441287.html)
- 【媒体，转引 LatePost】中国在线酒店预订 GMV 份额：携程系（含去哪儿、同程）约 70%，美团约 20%，飞猪约 5%–7% — [36Kr Europe](https://eu.36kr.com/en/p/3927354836383880)

**阶梯返佣 / override（收入取决于累计量而非单笔）**
- 【媒体/博客】Booking.com 联盟（affiliate）计划：联盟方拿 Booking.com 佣金的 25% / 30% / 35% / 40%，档位取决于当月 stayed bookings 数量，最低不低于 25%；各档的订单数门槛未能核实，Travelpayouts 渠道则是约 4% 订单金额的固定费率 — [UpPromote directory](https://uppromote.com/affiliate-directory/booking-com/)；[Travelpayouts](https://www.travelpayouts.com/en/offers/bookingcom-affiliate-program)
- 【媒体/博客】override commission 的行业定义：在基础佣金之外、按销量达标支付的追加佣金，通常是超过预定目标部分销售额的一个百分比，可分档递增；示例是代理商一年内订满某连锁酒店 20 万美元后触发 — [AltexSoft glossary](https://www.altexsoft.com/glossary/override-commission/)

### Inferences
- 自算（输入来自上面的 10-K）：Booking Holdings 2024 年 merchant take rate ≈ 141.42/1,041.82 = 13.6%，agency take rate ≈ 85.24/613.98 = 13.9%；每 room night 的佣金类收入上限 ≈ (141.42+85.24)亿/11.44亿 ≈ 19.8 美元（分子含机票、租车等非住宿收入，所以偏高）。Expedia Group 2024 年 revenue margin ≈ 136.91/1,109.21 = 12.3%，lodging revenue per room night ≈ 109.50亿/3.839亿 ≈ 28.5 美元（混合 B2C 与 B2B）。
- 公式里的"平台佣金"参数可以按三层设置：基础佣金 8%–15%（日本本土平台 8%–10%，国际平台在日本 12%，全球约 15%）；常驻合作项目 +2~3 个百分点；临时加价另算且无公开上限。这些区间是对上面不同质量来源的归纳，不是任何单一平台的官方表。
- 阶梯返佣的存在意味着"单笔收入"不是常数：若要模拟"累计订单达到门槛后费率跳档"，可参照 affiliate 的 25%→40% 结构，把边际一单的收入写成累计量的函数。酒店侧对 OTA 的按量返佣我没有找到公开证据。
- 携程案说明"把排序（流量分配）与商业条款绑定"在 2026 年已是反垄断执法对象，而不仅是消费者保护问题；用排序惩罚不配合的合作方属于高风险设计。

### Gaps
- 美团、飞猪的酒店佣金率没有找到官方或可追溯的具体数字；只有"8%–15%"之类的泛称。
- 楽天トラベル、じゃらん没有找到面向住宿设施的官方费率页面，全部是第三方整理，且 2025 与 2026 口径不一致。
- Booking.com Partner Help 页面直接抓取返回 403，Expedia sort-order 页面返回 429；上面标【检索摘要】的条目需在浏览器中核对原文。Preferred / Preferred Plus 的具体加点数官方页面只说"small commission increase"，3 个百分点来自 DCCA 报告和第三方指南。
- Agoda 的 10%/12%/15% 是"在基础佣金之上的增量"还是"合计费率"，从摘要无法确定；Agoda 非推广酒店的基础佣金未核实。
- Trip.com（国际站）、Tripadvisor、Google Hotel Ads 的佣金或 CPC 水平本次未查到可靠数字。

## 2. 排序实践：排序目标、佣金如何进入排序、自然与赞助混排、position bias、多目标

### Takeaway
公开材料显示的共同做法是：主排序模型以预订概率（或点击、预订、扣除取消后的预订）为目标，佣金或补偿作为排在相关性与质量之后的次级因素或加权项进入，赞助位单独拍卖并贴标签。学术界对同一份 Expedia 数据的估计显示，按消费者效用排序与按转化排序几乎不冲突，而以佣金为主导的提升会大幅改变排位（丹麦监管机构估计常驻+临时提升可把一家普通酒店从第 397 位推到第 114 位）。

### Cited Findings

**平台自述的排序目标与佣金位置**
- 【官方，2025】Booking.com：排名取决于点击、总预订、扣除取消后的预订三项表现，这些又取决于 review scores、availability、policies、pricing；佣金高低、付款速度、Genius/Preferred 身份是"other things"— [Booking.com How we work](https://www.booking.com/content/how_we_work.en-gb.html)
- 【官方，检索摘要】Expedia：排序优先级为 Offer Strength、Quality Score、compensation；佣金在"similar offers"之间决定相对顺序 — [Expedia sort order info](https://www.expedia.com/lp/b/sort-order-info)
- 【学术】Expedia 的赞助酒店（标注"sponsored"）可以付费出现在指定位置，同时该酒店也会出现在自然排序中（约 2019 年的情况）— [Eisfeld, How Do Online Product Rankings Influence Sellers' Pricing Behavior?](https://luiseeisfeld.github.io/assets/docs/HotelRankings_Eisfeld_TSE.pdf)
- 【审计/官方，2024】trivago 的 marketplace 是广告主为每次点击出价的 CPC 竞价 — [trivago FY2024 Form 20-F](https://www.sec.gov/Archives/edgar/data/1683825/000168382525000013/trvg-20241231.htm)

**工程论文与博客**
- 【学术，KDD 2019】Airbnb "Applying Deep Learning to Airbnb Search"：标签是是否预订（booked=1，其余=0）；损失函数从 L2 regression 演进到 pairwise 的 lambdarank（按交换两个位置带来的 NDCG 变化加权）；离线指标 NDCG；最终 DNN 两个隐层、195 个输入特征、训练样本 17 亿对；把 listing ID 做 embedding 会过拟合（一个 listing 一年最多被订 365 次）；预订 + long view 的多任务模型使 long view 大增但预订持平 — [arXiv:1810.09591](https://ar5iv.labs.arxiv.org/html/1810.09591)
- 【学术，KDD 2020】Airbnb "Improving Deep Learning for Airbnb Search"：后续改进集中在网络结构、positional bias、cold start — [arXiv:2002.05515](https://arxiv.org/pdf/2002.05515)
- 【学术，2023】Airbnb "Optimizing Airbnb Search Journey with Multi-task Learning"（Journey Ranker）：把中间的 guest 行为作为正向和负向 milestone，平衡 guest 与 host 偏好，已部署到 4 个 Airbnb 产品；摘要未给具体数字 — [arXiv:2305.18431](https://arxiv.org/abs/2305.18431)
- 【学术，2017 workshop】Expedia "A Multi-Objective Learning to re-Rank Approach to Optimize Online Marketplaces for Multiple Stakeholders"：从面向消费者的初始排序出发做 re-rank，中介的目标是"maximize its commission"，同时用基于 Kendall tau 的正则项约束新排序贴近原排序；在 Expedia 酒店数据上优于业务规则基线；摘要无数字 — [arXiv:1708.00651](https://arxiv.org/abs/1708.00651)
- 【官方工程博客】Expedia Group Tech：lodging ranking 用 learning-to-rank，明确存在 selection bias 与 position bias — [Choosing the Right Candidates for Lodging Ranking](https://medium.com/expedia-group-tech/choosing-the-right-candidates-for-lodging-ranking-d0841bf40c0e)；[Personalized Ranking Model for Lodging](https://medium.com/expedia-group-tech/personalized-ranking-model-for-lodging-5be43ae975fe)
- 【学术，CIKM 2023】Fliggy "MERIT: A Merchant Incentive Ranking Model for Hotel Search & Ranking"：在消费者兴趣与平台收入之外加入商家质量目标（MCI score），两周在线测试 CVR +1.50%、Sales Volume +0.97%、展示酒店的平均 MCI +3.02% — [ACM DL](https://dl.acm.org/doi/pdf/10.1145/3583780.3614964)；[arXiv:2506.08442](https://arxiv.org/html/2506.08442)
- 【学术，会议未核实】Fliggy "Prices Do Matter: Modeling Price Competitiveness for Online Hotel Industry"：四周在线测试 GMV 相对提升 3.2%、CVR 相对提升 4.9% — [ResearchGate](https://www.researchgate.net/publication/390545664_Prices_Do_Matter_Modeling_Price_Competitiveness_for_Online_Hotel_Industry)
- 【学术，期刊】Meituan-Hotel "Deep click interest network for reranking hotels"：上线后 CTCVR +2.40%、CTR +1.09% — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0952197623018596)
- 【学术，KDD 2019，二手摘要】Booking.com "150 Successful Machine Learning Models: 6 Lessons Learned at Booking.com"：离线模型指标不等于业务指标，模型价值靠 randomized controlled trials 衡量 — [The Morning Paper 摘要](https://blog.acolyer.org/2019/10/07/150-successful-machine-learning-models/)

**position bias 与排序因果效应**
- 【学术，Marketing Science 2018】Ursu "The Power of Rankings"：利用 Expedia 随机排序实验，排名影响消费者搜索哪些酒店，但在已点击的条件下基本不改变购买；平均 position effect 估计为 1.92 美元；Expedia 做随机排序是为了得到不受位置偏差影响的训练数据，代价是这部分流量成交更少 — [INFORMS](https://pubsonline.informs.org/doi/fpi/10.1287/mksc.2017.1072)；[学位论文版](https://knowledge.uchicago.edu/record/1646/files/Ursu_uchicago_0330D_13283.pdf)
- 【学术，arXiv v5】Greminger（同一份 Expedia 数据）：随机排序样本中每上移一位，点击概率约 +0.14 个百分点，对预订的直接位置效应不显著（0.0028 个百分点）；位置效应随价格升高而变小；反事实排序里，按效用排序同时最大化转化与消费者福利（"no trade-off between these two objectives"），收入与消费者福利之间的取舍"limited"：相对随机排序，福利最大化排序收入 +11.1%，Bottom-Up 排序收入约 +18.0% — [arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【监管，2020 年秋数据】DCCA 对一家大型 OTA 的抓取：785 次搜索、68 个城市、443,232 条结果、47,673 家酒店；第一页（第 1–25 位）85.5% 的结果带常驻提升，第二页 74.2%；临时提升在第一页占 11.8%，前 5 位占 18.9%；回归估计一家"基准酒店"自然排名 397，同时买常驻和临时提升后为 114（上升 283 位），仅常驻提升约上升 140 位 — [DCCA 2023](https://kfst.dk/media/v0snxsvj/ranking-boosts.pdf)
- 【学术，Marketing Science 2020】Hunold, Kesler, Laitenberger "Rankings of Online Travel Agents, Channel Pricing, and Consumer Protection"：研究 OTA 是否在酒店于其他渠道定价更低时给出更差的排位；工作论文版结论是 OTA 调整搜索结果以约束酒店在竞争渠道的低价，降低了搜索质量 — [INFORMS](https://pubsonline.informs.org/doi/fpi/10.1287/mksc.2019.1167)；[ZEW 工作论文](https://www.zew.de/fileadmin/FTP/dp/dp18059.pdf)
- 【学术，Marketing Science 2012】Ghose, Ipeirotis, Li "Designing Ranking Systems for Hotels on Travel Search Engines by Mining User-Generated and Crowdsourced Content"：用随机系数结构模型估计每家酒店给消费者带来的期望效用并据此排序，数据为 1,497 家美国酒店，数千人的用户研究偏好该效用排序 — [INFORMS](https://pubsonline.informs.org/doi/fpi/10.1287/mksc.1110.0700)

### Inferences
- "score = P(预订) × 收入"与公开做法方向一致，但平台自述里佣金的位置都排在转化与质量之后（Booking 是"other things"，Expedia 是第三优先级且只在相近报价间起作用）。把佣金做成乘法项时，若不加约束，其效果会比平台自述的更激进。
- Booking 把"扣除取消后的预订"作为排序三要素之一，Airbnb 把负向 milestone 纳入多任务，说明 P(预订) 应该是"成交且不取消"的概率，取消率需要单独建模或折算。
- Expedia 2017 的 re-rank 思路（先得到面向用户的排序，再在"不偏离原排序太远"的约束下优化佣金）正好对应"对合作酒店推力设上限"的要求：上限可以直接定义为新旧排序的 Kendall tau 距离或最大位移。
- Greminger 的结论（效用排序与转化不冲突，收入与福利取舍有限）支持把用户效用模型作为 P(预订) 的主体，再让收入项只做有界调整；这是从一份 2012–2013 年数据的结构模型反事实得出的，不是线上实验结果。
- DCCA 的数字给了"无上限时会发生什么"的参照：第一页 85.5% 都是付费提升，提升变成入场费，排序与自然质量脱钩。

### Gaps
- 没有找到 Booking.com、Trip.com、Agoda、Tripadvisor 公开描述"佣金在排序函数中的具体权重或公式"的论文或博客；平台只披露"是因素之一"。
- 没有找到任何平台公开的"赞助位占比上限"数字。
- Airbnb 2023 论文的具体任务列表和线上增益、Booking.com KDD 2019 论文原文本次未直接读到，只有摘要或二手总结。
- Hunold et al. 的排位惩罚幅度数字未提取；正式发表版的结论表述需对照原文。

## 3. 预订决策因素的量化证据：选择模型、WTP、转化率、决策周期

### Takeaway
公开证据里方向最稳定的因素是价格（负）、星级与评分（正）、位置（正）、促销标记（正）和列表位置（靠前更易被点击）；可直接引用的量级有：香港陈述性选择实验中在线评分每多一颗星值约 18 美元、到地铁站步行每少一分钟值约 5.9 美元，Expedia 数据里价格系数约为每 100 美元 −0.242。决策周期长：Expedia Group 2023 年研究显示从动念到预订平均 71 天，预订前 45 天内浏览 141 个页面。

### Cited Findings

**Expedia 数据（revealed preference，2012-11 至 2013-06）**
- 【学术】样本描述（随机排序子样本 51,510 个 session，全样本 166,039 个，约 30% 为随机排序）：每个列表平均 26.35 家酒店（5–38）；平均价格 171.70 美元（中位数 141.04）；星级均值 3.34；review score 均值 3.81；location score 均值 3.26；连锁占 62%；24% 带促销；行程均长 3.07 天；booking window 均值 53.67 天、中位数 31 天；成人 2.08、儿童 0.43、房间 1.14；每 session 平均点击 1.14 次，约 8% 的 session 以预订结束 — [Greminger, arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【学术，表格抓取时列对齐有瑕疵，数值需对照原文】同一论文的线性概率模型（随机排序、单位为百分点）：价格每 +1 美元，点击 −0.0173、预订 −0.0017；星级每 +1，点击 +2.16、预订 +0.12；review score 每 +1，预订 +0.079（对点击不显著）；连锁 +0.31 / +0.064；location score 每 +1，+0.56 / +0.056；促销标记 +1.50 / +0.14；位置每上移一位，点击 +0.14 — [Greminger, arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【学术】结构模型：价格系数 −0.242（每 100 美元）；多发现一家酒店的 discovery cost 约 6 美分；click cost 约 2.82 美元 — [Greminger, arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【学术】Ursu 的顺序搜索模型：平均 position effect 1.92 美元，低于此前没有实验变异的文献估计 — [Ursu, Marketing Science 2018](https://pubsonline.informs.org/doi/fpi/10.1287/mksc.2017.1072)

**陈述性选择实验（stated preference）**
- 【学术，2017-06 调查】Masiero et al. "Understanding hotel location preference of customers: Comparing random utility and random regret decision rules"：香港 719 名游客，每题 3 个备选酒店；属性含到最近地铁站、顶级购物区、顶级景点的步行时间、街区类型、在线评分、价格；估计 MNL 与 mixed logit（500 Halton draws、正态随机系数）。RUM-MNL 的 WTP：到地铁站每少走 1 分钟 5.9 美元，到购物区 1.2 美元，到景点 0.7 美元；海滨步道相对主干道 +58 美元；在线评分每多一颗星 +18 美元；RRM 模型下到地铁站的 WTP 随对比情境在 2.9–25.6 美元/分钟之间变化 — [PolyU 机构库全文](https://ira.lib.polyu.edu.hk/bitstream/10397/99277/1/Masiero_Understanding_Hotel_Location.pdf)
- 【学术】Masiero, Heo, Pan "Determining guests' willingness to pay for hotel room attributes with a discrete choice model"：香港一家酒店的陈述性选择实验 + mixed logit，给房景、楼层、行政酒廊、免费 minibar、智能手机服务、取消政策定价（具体金额本次未提取）— [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0278431915000912)
- 【学术，发表年份未核实】"Strategic consumer behavior in online hotel booking"：离散选择实验显示 booking window 越长，免费取消价的效用越高，且该效应随风险偏好上升而减弱 — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0160738320300918)

**评分对价格与销量的影响**
- 【学术/行业研究，2012】Anderson（Cornell CHR）"The Impact of Social Media on Lodging Performance"：ReviewPRO 100 分制指数每 +1 分，ADR 最多 +0.89%、入住率 +0.54%、RevPAR +1.42%；Travelocity 数据：5 分制评分 +1 分（如 3.3→4.3），酒店可提价 11.2% 而保持同样的入住率或份额 — [Cornell eCommons](https://ecommons.cornell.edu/entities/publication/d64bbbba-651a-4e13-a058-af3e2e82f4cf)；[Hospitality Net 报道](https://www.hospitalitynet.org/news/4058547.html)
- 【学术，2011】Ye, Law, Gu, Chen：旅客评分提高 10%，在线预订量提高 5% 以上 — [PolyU 研究门户](https://research.polyu.edu.hk/en/publications/the-influence-of-user-generated-content-on-traveler-behavior-an-e/)
- 【学术】Öğüt & Taş：在线顾客评分提高 1%，每间房销量在巴黎最多 +2.68%、伦敦最多 +2.62% — [EconPapers](https://econpapers.repec.org/RePEc:taf:servic:v:32:y:2010:i:2:p:197-214)
- 【厂商营销】TrustYou 与 NYU 的模拟：价格相同时，旅客选择评分更高酒店的可能性是 3.9 倍 — [TrustYou](https://www.trustyou.com/blog/insights/travel-reviews-impact-hotel-conversion-rates-pricing/)

**排名与折扣的相对效力**
- 【监管，2023】DCCA 在线选择实验（1,114 名消费者，平均年龄 50.4；酒店随机分到中性、降价 10%、排名提升 10 或 20 位并带"已提升"标记、两者叠加）：提升 10 位对被选概率的影响是降价 10% 的 3.5 倍，提升 20 位是 5 倍 — [DCCA 2023](https://kfst.dk/media/v0snxsvj/ranking-boosts.pdf)

**取消率**
- 【厂商报告，2024–2025】D-Edge（酒店分销技术商）口径：Booking 系渠道取消率 37.2%（2024-10 数据），GDS 约 4.6%；2024 Hotel Distribution Report 称各渠道取消率在 18%–42% 之间；亚太地区整体取消率 2024 年 14.3%、2025 年 13.4%，Booking.com 约四分之一订单被取消，接近直销渠道的三倍。这些数字来自不同年份和地区，不可直接横比 — [D-Edge Hotel Distribution Report 2024](https://www.d-edge.com/wp-content/uploads/2024/04/Hotel-Distribution-Report-2024-EN.pdf)；[Hospitality Net](https://www.hospitalitynet.org/news/4124422/how-to-prevent-hotel-no-show-and-last-minute-cancellations)；[PhocusWire APAC](https://www.phocuswire.com/news/distribution/apac-hotel-distribution-slower-growth-rising-regional-otas-direct-channels-under-pressure)

**转化率与决策周期**
- 【厂商研究，2023】Expedia Group "Path to Purchase"（Luth Research 被动计量，7 个市场 70,000+ 参与者，分析预订前 45 天）：平均花 303 分钟看旅行内容，浏览 141 个页面（美国 277 个）；早期每天约 2.5 个页面，预订当天 25 个；从动念到预订平均 71 天（灵感阶段 33 天 + 研究规划 38 天）；80% 的人在这 45 天内用过 OTA — [Expedia newsroom](https://www.expedia.com/newsroom/eg-path-to-purchase-research)；[Expedia Group Partner blog](https://partner.expediagroup.com/en-us/resources/blog/travelers-booking-behavior-path-to-purchase-marketing-strategies)
- 【厂商/博客】酒店官网转化率的经验值约 2%（各来源 1.5%–3%），口径不统一（分母有的是访客、有的是 session）；Unbounce 2024 报告给出住宿类落地页中位转化率 3.7% — [Hospitality Net](https://www.hospitalitynet.org/viewpoint/125000226/126002466.html)；[Unbounce](https://unbounce.com/conversion-benchmark-report/travel-hospitality-conversion-rate/)

### Inferences
- 自算：Greminger 样本里每次曝光的点击率 ≈ 1.14/26.35 ≈ 4.3%，每次曝光的预订率 ≈ 0.08/26.35 ≈ 0.30%。这可以作为模拟用户时 P(预订) 的量级校准，但该 Kaggle 数据的 session 入样条件（是否只含有点击的搜索）我没有核实，8% 很可能高于真实 OTA 的 session 转化率。
- 香港实验的 WTP 给出了属性之间的换算比：一颗在线评分星（18 美元）约等于离地铁站近 3 分钟步行（5.9 美元/分钟）。用于日本城市酒店时可以保留"比值"，绝对金额需按当地房价重新标定。
- 评分弹性的三项研究量级不同（10% 评分→5%+ 预订；1% 评分→约 2.6% 每房销量），差异来自地区、年份和因变量定义；手设权重时只适合取"评分是仅次于价格的强正向因素"这一结论，不适合直接套用系数。
- DCCA 的结果（10 个位次 > 10% 折扣）说明排序位置本身对选择的影响大于中等幅度的价格变化，因此"排序被商业因素推动了多少位"是比"加了多少权重"更贴近用户影响的度量。
- 71 天、141 个页面意味着单次会话内的"预订"很少发生；对话式规划 demo 的 P(预订) 更合理的定义是"进入下一步（保存、点击外链、确认方案）"的概率，再乘以一个会话到成交的折算系数。

### Gaps
- 没有找到专门针对日本酒店或访日游客的离散选择模型系数或 WTP。
- 照片质量、品牌、同行人构成、提前期对预订概率的量化系数本次没有找到可直接引用的来源（Expedia 数据里有 chain、儿童数、booking window 字段可自行拟合）。
- 免费取消对转化的因果提升没有找到严格研究；只有度假租赁运营商的内部对比和调查。
- OTA 自身的 session 转化率或 look-to-book 没有审计口径数字；2% 左右只是酒店官网的经验值。
- Greminger 结构模型中星级、评分等系数的抓取结果符号可疑，未采用；需读原文表格。

## 4. 可离线使用的公开数据集

### Takeaway
唯一同时具备曝光列表、价格、点击标签、预订标签、促销标记和随机排序标记的公开数据是 Kaggle 的 Expedia "Personalize Expedia Hotel Searches"（ICDM 2013），约 992 万行训练数据，最适合拟合 P(预订)。其余数据集要么只有点击（trivago）、只有成交序列（Booking.com）、要么不含酒店级特征（Airbnb New User Bookings），且多数只许非商业研究使用。

### Cited Findings
- 【学术 + Kaggle】Expedia "Personalize Expedia Hotel Searches"（ICDM 2013）：训练集 399,344 个搜索列表、9,917,530 行，测试集 266,230 个列表、6,622,629 行；相关性标签为预订=5、点击=1、其他=0；评测指标 NDCG@38；下载地址为 Kaggle 竞赛页，文件为 train.csv — [Kaggle: expedia-personalized-sort](https://www.kaggle.com/c/expedia-personalized-sort)；[参赛队论文 arXiv:1311.7679](https://arxiv.org/pdf/1311.7679)
- 【开源库文档】该数据的可用字段（choice-learn 的加载器使用）：搜索级 `srch_length_of_stay`、`srch_adults_count`、`srch_children_count`、`srch_room_count`、`srch_saturday_night_bool`、`booking_window`、`random_bool`、`site_id`、`visitor_location_country_id`、`srch_destination_id`；酒店级 `prop_starrating`、`prop_review_score`、`prop_brand_bool`、`prop_location_score1`、`prop_location_score2`、`prop_log_historical_price`、`position`、`promotion_flag`、`orig_destination_distance`、价格；加载器把每个搜索补齐到 38 个候选并加入"不购买"选项 — [choice-learn Expedia dataset reference](https://artefactory.github.io/choice-learn/references/datasets/references_expedia/)
- 【二手资料】字段含义：`booking_bool` 用户是否预订、`click_bool` 是否点击、`promotion_flag` 酒店是否展示了促销价、`random_bool` 展示顺序是否随机、`position` 仅训练集有 — [课程作业转载的字段表](https://www.scribd.com/document/756181959/Assignment-2)
- 【学术】同一数据约 30% 的 session 为随机排序，时间范围 2012-11 至 2013-06 — [Greminger, arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【Kaggle，二手描述】Expedia Hotel Recommendations（2016）：约 3,700 万条点击与预订记录、120 万用户、2013–2014 年；预测目标是 `hotel_cluster`（Expedia 把酒店按热度、星级、评分、价格、距市中心距离、设施聚成 100 类）— [Kaggle 数据页（经 GitHub 项目引用）](https://www.kaggle.com/c/expedia-hotel-recommendations/data)；[数据说明转述](https://github.com/BethHilbert/Python-Expedia)
- 【官方】trivago RecSys Challenge 2019：官方下载页提供 train.csv、test.csv、item_metadata.csv 及 ground truth；许可为"solely for the purposes of research and development of data science for non-commercial purposes"，禁止商业使用；要求引用数据集论文 DOI 10.1145/3412379。一篇论文统计为 981,655 名用户、927,142 家酒店、1,202,064 个 session、19,715,327 次行为（该论文自己的预处理口径）— [trivago RecSys Challenge 2019 data sets](https://recsys2019data.trivago.com/)；[RecSys Challenge 2019 GitHub](https://github.com/recsyschallenge/2019)；[trivago benchmarks](https://github.com/trivago/recsys-challenge-2019-benchmarks)
- 【官方】Booking.com Multi-Destination Trips Dataset（WSDM WebTour 2021）：训练集 1,166,835 条匿名预订，评测集 378,667 条；字段 `user_id`、`checkin`、`checkout`、`created_date`、`affiliate_id`、`device_class`、`booker_country`、`hotel_country`、`city_id`、`utrip_id`；Hugging Face 标注许可 CC BY-NC-ND 4.0，条款写明数据归 Booking.com 所有、不得商用、不得用于与 Booking.com 竞争；引用 Goldenberg & Levin, SIGIR 2021 — [GitHub: bookingcom/ml-dataset-mdt](https://github.com/bookingcom/ml-dataset-mdt)；[Hugging Face](https://huggingface.co/datasets/Booking-com/multi-destination-trip-dataset)
- 【Kaggle，二手描述】Airbnb New User Bookings：train_users 约 213,451 人、test_users 62,096 人，sessions 表超过 1,000 万条行为记录；目标是新用户首次预订的 `country_destination`（含"未预订"类别）；不含房源级曝光与价格 — [竞赛复盘](https://purcelba.github.io/Kaggle-airbnb/)；[Medium 案例](https://medium.com/analytics-vidhya/airbnb-new-user-prediction-a-kaggle-case-study-e26e712fe8d2)
- 【学术，CC BY 4.0】Antonio, de Almeida, Nunes "Hotel booking demand datasets"（Data in Brief 2019）：葡萄牙一家城市酒店与一家度假酒店的 119,390 条预订（2015-07 至 2017-08），31 个变量，含是否取消、lead time、deposit type、ADR — [ResearchGate](https://www.researchgate.net/publication/329286343_Hotel_booking_demand_datasets)；[GitHub 项目说明许可](https://github.com/mcleblanc711/hotel-rm-research)
- 【官方】楽天トラベルデータ：国立情报学研究所（NII）IDR 自 2010 年起向大学和公共研究机构提供"楽天データセット"，按合同使用；2025-12-16 公告更新了楽天トラベル数据；引用格式 DOI 10.32130/idr.2.2 — [数据集 DOI](https://doi.org/10.32130/idr.2.2)；[NII IDR 用户论坛资料](https://www.nii.ac.jp/dsc/idr/userforum/poster/IDR-UF2025_Rakuten.pdf)
- 【二手描述】Fliggy 天池数据集（编号 113649）：约 200 万随机用户 2019-06 至 2021-06 的点击、收藏、加购、支付行为（`clk`/`fav`/`cart`/`pay`），结构类似 MovieLens-20M — [Fliggy-SMINet-AAAI2022 仓库说明](https://github.com/wanjietao/Fliggy-SMINet-AAAI2022)
- 【开源库】choice-learn 支持 Conditional Logit、Nested Logit、Mixed Logit、Latent Class；torch-choice 支持 conditional logit 与两层 nested logit，可用 GPU — [choice-learn JOSS 论文](https://joss.theoj.org/papers/10.21105/joss.06899.pdf)；[torch-choice arXiv:2304.01906](https://arxiv.org/html/2304.01906v4)

### Inferences
- 拟合 P(预订) 的首选是 Expedia ICDM 2013：它的 `random_bool=1` 子集可以在没有位置偏差的条件下估计属性效应，`promotion_flag` 可以近似"平台推广标记"的效果，`position` 可以估计位置效应。它没有佣金字段，收入项只能外接假设的佣金表。
- trivago 数据的标签是 clickout（跳转到广告主），不是成交；这与 trivago 按点击收费的模式一致（见第 1 节 20-F）。它适合做会话内意图和点击预测，不适合直接校准预订概率。
- Booking.com 数据只有已成交的行程序列，没有曝光和价格，适合"下一站城市"这类行程级任务，不适合酒店排序。
- Antonio 数据可用来拟合取消概率（lead time、deposit type 等），与 Expedia 数据拼成"预订 ×（1−取消）"。
- 许可方面：trivago 与 Booking.com 明确限非商业；楽天数据面向高校和公共研究机构，个人开发者大概率拿不到；作为个人作品集 demo 使用非商业数据问题不大，但公开发布模型权重或派生数据前应逐一核对条款。

### Gaps
- Expedia ICDM 2013 的 Kaggle 数据使用条款没有核实（Kaggle 页面需登录并接受竞赛规则）；`gross_bookings_usd`、`comp*` 竞品价格等字段的官方定义也未直接读到。
- trivago 官方下载域名在本次抓取时无法解析（DNS 失败），是否仍可下载未确认；Kaggle 上有第三方镜像但许可标为 Unknown。
- 没有找到任何带"佣金率"或"是否合作酒店"字段的公开酒店数据集。
- 没有找到日本市场、可由个人获取的酒店搜索或预订日志数据集。
- Airbnb New User Bookings 的 Kaggle 页面 URL、Fliggy 天池数据集的许可条款未直接核实。

## 5. 付费排序的信任与监管边界

### Takeaway
欧盟、英国、美国、中国都要求把"因付款而获得的排位"明确标识为广告或披露其影响；澳大利亚对 trivago 的 4,470 万澳元罚款和中国对携程的 51.79 亿元罚没说明执法已经落到排序算法本身。实证上，排名提升对用户选择的拉动大于降价、赞助结果的相关性更低，而标签写得越直白用户点得越少，所以"披露 + 质量门槛 + 推力上限"是可辩护的组合。

### Cited Findings

**欧盟**
- 【法规】Omnibus Directive (EU) 2019/2161 在 UCPD 附件一新增第 11a 项：响应消费者搜索时提供结果，却不清楚披露付费广告或专门为获得更高排名而支付的款项，属于在任何情况下都不公平的商业行为；并新增向消费者说明决定排序的主要参数的义务；"ranking"定义为经营者呈现、组织或传达商品时给予的相对显著度，不论技术手段；成员国 2021-11-28 前转化，2022-05-28 起适用 — [EUR-Lex: Directive (EU) 2019/2161](https://eur-lex.europa.eu/eli/dir/2019/2161/oj/eng)；[Article 3 文本](https://www.legislation.gov.uk/eudr/2019/2161/article/3/data.htm)
- 【法规解读，二手】P2B Regulation (EU) 2019/1150 第 5 条要求在线中介服务在条款中说明主要排序参数及其相对重要性的理由；第 5(3) 条针对排名可被直接或间接付款影响的情形（如 ranking booster、preferred-partner programme）设披露义务 — [欧委会 P2B 排序透明度指南（转载）](https://mbkaya.com/it-law-eu-commission-p2b-ranking-transparency-guideline-2020-c-424-01/)
- 【法规解读，二手】DSA 第 27 条要求平台以通俗语言说明推荐系统的主要参数和用户可用的调整选项；第 26 条要求对广告投放的主要参数透明 — [Pinsent Masons 分析](https://www.pinsentmasons.com/en-gb/out-law/analysis/how-the-digital-services-act-changes-things-for-platforms)
- 【官方】Booking Holdings 年报确认 Booking.com 被欧委会依 DMA 指定为 gatekeeper，并属于 DSA 下的 Very Large Online Platform；欧委会 2024-05-13 的指定给了 6 个月合规期 — [Booking Holdings FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000010/bkng-20241231.htm)；[Fortune 2024-05-13](https://fortune.com/europe/2024/05/13/booking-european-commission-antitrust-monopoly-core-platform-service/)
- 【监管】欧盟 CPC 消费者保护网络：Booking.com 于 2019-12-18、Expedia Group 于 2020-12-18 承诺改变向消费者呈现报价、折扣和价格的方式 — [European Commission: Accommodation booking](https://commission.europa.eu/topics/consumers/consumer-rights-and-complaints/enforcement-consumer-protection/coordinated-actions/accommodation-booking_en)
- 【律所解读，2026-11】欧委会 2026-11-11 提出 Digital Fairness Act 提案：以条例形式取代 2005 年 UCPD，罚款最高为全球年营业额 6%，列入 10 类一律视为不公平的 dark patterns，并涉及个性化、动态定价、drip pricing。提案中关于排序或付费位的具体条款本次未查到，立法过程中文本仍会变化 — [Lewis Silkin](https://www.lewissilkin.com/insights/2026/11/11/european-commission-publishes-long-awaited-digital-fairness-act-102o9b5)；[Osborne Clarke](https://www.osborneclarke.com/insights/proposed-eu-digital-fairness-act-targets-addictive-design-dark-patterns-and-unfair)

**英国**
- 【监管，2019】CMA 对住宿预订网站的原则：若平台从预订或点击中赚到的钱影响结果顺序，必须"prominently tell customers"；付费获得固定或置顶位置的要说明；"clearly differentiate 'paid for' listings with those that aren't"；另含折扣声明、隐藏费用、压力销售三类原则；整改期限 2019-09-01 — [CMA short guide](https://www.gov.uk/government/publications/online-hotel-booking-principles-for-businesses/being-transparent-with-your-customers-a-short-guide-for-online-accommodation-booking-sites)
- 【监管，2019】Expedia、Booking.com、Agoda、Hotels.com、ebookers、trivago 六家于 2019-02 作出承诺，包括说明佣金如何影响搜索结果；2019-09-13 另有 25 家签署全行业原则 — [CMA press release](https://www.gov.uk/government/news/major-overhaul-of-hotel-booking-sector-after-cma-action)；[CMA case page](https://www.gov.uk/cma-cases/online-hotel-booking)
- 【媒体，2019】MoneySavingExpert 检查 14 个预订网站，其中 8 个（含 Booking.com、Expedia、Kayak）在排序中考虑佣金等商业因素并已向用户说明 — [MoneySavingExpert 2019-10](https://www.moneysavingexpert.com/news/2019/10/travel-booking-sites-factor-in-commission-when-ran)

**澳大利亚**
- 【监管/法院，2020–2022】ACCC v Trivago：联邦法院 2020-01 认定 trivago 的算法偏向支付更高 cost-per-click 的在线酒店预订网站，却把置顶报价表现为最便宜；2020-11 上诉被驳回；2022-04 判罚 4,470 万澳元 — [ACCC 2022 media release](https://accc.gov.au/media-release/trivago-to-pay-447-million-in-penalties-for-misleading-consumers-over-hotel-room-rates)；[ACCC 2020 media release](https://accc.gov.au/media-release/trivago-misled-consumers-about-hotel-room-rates)
- 【媒体，转述判决】法院认定 trivago 的置顶报价在 66.8% 的情况下不是最便宜的 — [Mumbrella](https://mumbrella.com.au/trivago-misled-consumers-66-8-of-the-time-by-favouring-highest-paying-advertisers-court-rules-613940)

**美国**
- 【监管，2013】FTC 工作人员更新 2002 年搜索引擎指引并致函通用搜索引擎及 17 家购物、旅行、本地搜索网站："including or ranking a search result in whole or in part based on payment is a form of advertising"，须用明显的底色或边框和清晰的文字标签与自然结果区分；垂直搜索中部分基于第三方付款的结果同样算广告 — [FTC press release 2013-06](https://www.ftc.gov/news-events/news/press-releases/2013/06/ftc-consumer-protection-staff-updates-agencys-guidance-search-engine-industry-need-distinguish)；[FTC 2013 letter](https://www.ftc.gov/sites/default/files/attachments/press-releases/ftc-consumer-protection-staff-updates-agencys-guidance-search-engine-industryon-need-distinguish/130625searchenginegeneralletter.pdf)
- 【监管，2025】FTC Rule on Unfair or Deceptive Fees（16 C.F.R. Part 464）2025-05-12 生效：短期住宿和现场演出票的广告价格必须一开始就给出含全部强制费用的总价，且总价比其他价格信息更醒目；适用于第三方平台和旅行代理 — [FTC FAQ](https://www.ftc.gov/business-guidance/resources/rule-unfair-or-deceptive-fees-frequently-asked-questions)；[Federal Register 2025-01-10](https://www.govinfo.gov/content/pkg/FR-2025-01-10/html/2024-30293.htm)

**日本**
- 【监管，2023】消費者庁依景品表示法第 5 条第 3 号，把"一般消費者が事業者の表示であることを判別することが困難である表示"指定为不当表示，2023-10-01 施行；规制对象是广告主事业者；运用基准要求用「広告」「プロモーション」「PR」等标示；违反者受措置命令 — [消費者庁 ステルスマーケティング](https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing)；[Impress Watch 解说](https://www.watch.impress.co.jp/docs/news/1489089.html)
- 【监管，2019–2022】公正取引委員会就宿泊预订网站的同等性条件（价格与房量不得劣于其他渠道）先后认定楽天トラベル（2019-10-25）、Booking.com（2022-03-16）、Expedia（2022-06-02）的確約計画；认定不等于认定违法 — [公取委 2022-03-16 Booking.com](https://www.jftc.go.jp/houdou/pressrelease/2022/mar/220316.html)；[公取委 2022-06-02 Expedia](https://www.jftc.go.jp/houdou/pressrelease/2022/jun/220602.html)

**中国**
- 【法规，2019-01-01 施行】《电子商务法》第四十条："对于竞价排名的商品或者服务，应当显著标明'广告'"；第十八条：按个人特征提供搜索结果的，应同时提供不针对个人特征的选项；第十九条：搭售须显著提示，不得设为默认同意；第十七条：全面、真实、准确、及时披露信息；第三十九条：不得删除消费者评价 — [《电子商务法》全文（维基文库）](https://zh.wikisource.org/wiki/中华人民共和国电子商务法)
- 【法规，2023-05-01 施行】《互联网广告管理办法》第九条：竞价排名的商品或者服务，广告发布者应当显著标明"广告"，与自然搜索结果明显区分 — [办法原文（JETRO 存档）](https://www.jetro.go.jp/ext_images/world/asia/cn/ip/law/pdf/origin/admin20230501.pdf)
- 【监管，2026-07-25】携程案（见第 1 节）：以流量分配机制强制独家和最低价，罚没 51.79 亿元 — [新华网](https://www.news.cn/fortune/20260725/cbf7170e42de4b0f8e81e83dd41a2709/c.html)

**付费或偏置排序伤害信任、选择质量的证据**
- 【监管，2023】DCCA：排名提升比降价更能吸引顾客，而消费者直接受益于降价、却不清楚如何受益于排名提升，鼓励酒店买排名而不是降价"may be detrimental to consumers"— [DCCA 2023](https://kfst.dk/media/v0snxsvj/ranking-boosts.pdf)
- 【监管，2026】丹麦提交 OECD 的说明：ranking boost 让商家可以不改善价格和质量就买到算法可见度 — [OECD DAF/COMP/WD(2026)31](https://one.oecd.org/document/DAF/COMP/WD(2026)31/en/pdf)
- 【学术，AIES 2024】"Sponsored is the New Organic"：Amazon 搜索结果中，排在自然结果之上的赞助结果按 Amazon 自己的排序标准相关性显著更低；作者建议对赞助结果设更严格的相关性门槛 — [AAAI/ACM AIES](https://ojs.aaai.org/index.php/AIES/article/download/31639/33806/35703)
- 【学术】132 人实验：对赞助链接的信任低于自然结果，消费者更不愿从赞助结果中的商家购买；披露商家可靠性信息可部分抵消 — [Effect of Sponsored Search on Consumer Trust and Choice](https://www.semanticscholar.org/paper/Effect-of-Sponsored-Search-on-Consumer-Trust-and-Ma-Liu/c035089752ad23b910ef355df4f3e69e59149d9e)
- 【学术】搜索引擎标签实地实验：把标签改为"Paid Advertisements"使广告点击比"Sponsored Link"或"Ad"少约四分之一 — [Advertising Disclosures: Measuring Labeling Alternatives in Internet Search Engines](https://www.researchgate.net/publication/228138367_Advertising_Disclosures_Measuring_Labeling_Alternatives_in_Internet_Search_Engines)
- 【学术，Marketing Science，反向证据】Sahni & Nair：餐厅搜索平台 20 万以上移动用户的随机实验，原生广告对广告主有效，在常用披露格式下未发现消费者被欺骗的证据 — [INFORMS](https://pubsonline.informs.org/doi/10.1287/mksc.2018.1125)
- 【学术】Hunold et al.：OTA 用排序约束酒店在其他渠道的低价，降低搜索质量（见第 2 节）— [ZEW 工作论文](https://www.zew.de/fileadmin/FTP/dp/dp18059.pdf)

**平台如何设门槛或上限**
- 【官方，检索摘要】Booking.com Preferred 只对前约 30% 合作方开放，须 review score ≥7、performance score ≥70%、对外价格有竞争力；Preferred Plus 限前 10% — [Booking.com Partner Help](https://partner.booking.com/en-gb/help/growing-your-business/increase-revenue/all-you-need-know-about-preferred-partner-programme)
- 【官方，检索摘要】Expedia 的补偿排在 Offer Strength 和 Quality Score 之后，且只在"similar offers"间调整相对顺序 — [Expedia sort order info](https://www.expedia.com/lp/b/sort-order-info)
- 【从业者博客，自述】一个未具名 marketplace 的做法：每类查询把相关性门槛设在自然相关性的第 60–70 百分位，低于门槛的付费条目不展示，并用 bias cap 限制付费相对自然的净优势；自述整体 CTR 约 +6%（QoQ）— [Sponsored Listings Without the Trust Tax](https://shadmanrahman.substack.com/p/sponsored-listings-without-the-trust)
- 【学术】统一估值的广告分配研究主张让广告与自然条目在同一个利润型指标上竞争，并设相关性与 ad load 的 guardrail — [More Ads, Happier Shoppers: Unified-Valuation Ad Allocation at Scale](https://link.springer.com/chapter/10.1007/978-3-032-16358-5_7)

### Inferences
- 各法域的共同底线可以压缩成三条：因付款或佣金而改变的位置必须披露或标"广告"；不能把付费位说成"最便宜"或"最适合"；用于个性化的排序要能说明主要参数。对话式 agent 推荐酒店时，"合作酒店"标识和"为什么推荐它"的理由字段是合规所需的最小披露。
- 可操作的"推力上限"至少有四种现成定义：进入门槛（评分、表现分位，Booking 的做法）；只在近似等价的候选之间用收入打破平局（Expedia 的表述）；相关性下限加净优势上限（从业者做法）；与纯用户效用排序的最大偏离（Expedia 2017 论文的 Kendall tau 约束）。公式里的"合作酒店推力项"可以从中任选一到两种并做成可审计的数字。
- 标签越直白点击越少（约四分之一）与"未发现欺骗"两项研究并不矛盾：披露会降低付费位的短期点击，但没有证据表明规范披露会损害平台整体。长期留存受损的直接因果证据本次没有找到，trust 惩罚项的系数只能作为假设参数。
- 日本的ステマ规制针对"看不出是广告的广告主表示"；平台自营排序里的合作酒店是否落入该告示，本次没有查到消費者庁的明确解释，稳妥做法仍是标示。

### Gaps
- 没有找到量化"付费排序导致用户留存或复购下降"的实证研究；现有证据是相关性下降、选择偏移和监管认定的误导。
- 没有找到 CMA 或欧委会给出的"多少比例消费者不知道排序受佣金影响"的调查数字；一篇 TSE 论文称消费者显著低估平台变现程度，但细节未核实 — [Zhao, Decoding rankings](https://www.tse-fr.eu/sites/default/files/TSE/documents/doc/document/Zhao_decoding_rankings.pdf)
- P2B 第 5 条和 DSA 第 26、27 条本次只读到二手解读，没有逐字核对 EUR-Lex 原文。
- Digital Fairness Act 提案中是否有针对排序或付费位的条款未确认。
- 日本针对 OTA 或比较网站排序的专门指引（除ステマ告示和公取委同等性条件案外）没有查到。

## 6. 行程级收入：活动、交通、打包产品的变现方式

### Takeaway
整份行程的收入主要仍来自住宿：Expedia Group 2024 年住宿占收入约 80%、机票约 3%；活动和体验的抽成比例最高（20%–30%），但客单价低；机票佣金接近于零。跨品类搭售已是可度量的指标，Booking.com 的"Connected Trip"交易在 2025 年占其总交易量的 low double-digit 百分比。

### Cited Findings
- 【审计/官方，2024，检索摘要】Expedia Group 收入构成：Lodging 109.50 亿、Advertising and media 9.54 亿、Air 4.28 亿、Other 13.59 亿美元 — [Expedia Group FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1324424/000132442425000008/expe-20241231.htm)
- 【审计/官方，2024】Trip.com Group：住宿预订 216 亿元、交通票务 203 亿元、打包旅游 43 亿元、合计 534 亿元人民币；交通票务收入 +10% 与票务 GMV +8% 基本同步 — [Trip.com Group FY2024 Form 20-F](https://www.sec.gov/Archives/edgar/data/1269238/000119312525078429/d779353d20f.htm)
- 【审计/官方，2024】Booking Holdings：机票 4,900 万张（+38.1%），机票 gross bookings +28%；租车 8,300 万天（+12.3%）— [Booking Holdings FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000010/bkng-20241231.htm)
- 【官方电话会 + 媒体，2025】Booking.com 把 connected transaction 定义为同一行程在其平台预订超过一个品类；2025 全年 Connected Trip 交易增长 high-20%，占 Booking.com 总交易的 low double-digit 百分比；2025 年 Q2 增长超过 30%，同期机票 +44% — [PhocusWire FY2025](https://www.phocuswire.com/booking-holdings-q4-full-year-2025-earnings)；[Q4 2025 电话会文字稿](https://s201.q4cdn.com/865305287/files/doc_financials/2025/q4/CORRECTED-TRANSCRIPT_-Booking-Holdings-Inc-BKNG-US-Q4-2025-Earnings-Call-18-February-2026-4_30-PM-ET.pdf)；[Travel Weekly](https://www.travelweekly.com/Travel-News/Travel-Technology/Booking-Holdings-q4-call-connected-trip)
- 【官方财报，2024】Viator（Tripadvisor）：2024 年收入 8.40 亿美元（+14%），gross booking value 接近 42 亿美元（约 +12%）；GBV 按预订时点计且未扣取消，收入按体验发生时点计且扣除取消 — [Tripadvisor 8-K 附件](https://capedge.com/filing/1526520/0000950170-25-023733/TRIP-8K/file/2)；[PhocusWire](https://www.phocuswire.com/tripadvisor-q4-2024-earnings)
- 【官方招股书，2025-11】Klook：2024 年 gross profit 2.578 亿美元，占 GTV 的 10.3%；2025 年前九个月 2.553 亿美元，占 GTV 的 11.1%；公司提示收入同时按净额与总额确认，收入口径的 take rate 不能代表经济实质。Skift 报道 2024 年 GTV 25 亿美元、收入 4.171 亿美元 — [Klook Form F-1](https://www.sec.gov/Archives/edgar/data/2071502/000121390025108023/ea0248324-08.htm)；[Skift 2025-11](https://skift.com/2025/11/10/klook-ipo-global-travel-experiences-future/)
- 【行业媒体，2025】GetYourGuide 通知部分供应商佣金自 2025-07-03 起由 20% 提高到 30%，部分运营商申诉后被撤回；合同要求至少提前四周书面通知。一位布达佩斯运营商称 Viator 对其基础佣金为 27% — [Arival](https://arival.travel/article/getyourguide-commission-increasing-for-some-operators)
- 【厂商指南】Klook 的供应商佣金不公开、逐家谈判，供应商工具商 Bókun 估计为 15%–35% — [Bókun](https://www.bokun.io/?p=6812)
- 【行业博客，日期与出处不清】航空公司对代理的机票佣金"little to no commission"，示例为部分航线 0–1%、个别航线 7%；旅行保险佣金 15%–35%（单一未注明来源的说法）— [AltexSoft](https://www.altexsoft.com/blog/how-travel-agents-get-paid/)

### Inferences
- 自算：Viator 2024 年收入/GBV ≈ 8.40/42 ≈ 20%（两者时点和取消口径不同，只是近似）；Klook 2024 年收入/GTV ≈ 4.171/25 ≈ 16.7%，毛利/GTV 10.3% 更接近经济意义上的抽成；Expedia Group 收入中住宿约占 80.0%、机票约 3.1%、广告约 7.0%；Trip.com Group 收入中住宿约 40%、交通约 38%、打包旅游约 8%。
- 行程级"合并收入"可以写成各品类的 Σ(成交概率 × 金额 × 该品类抽成)：住宿 8%–15%，活动与门票 10%–30%（平台净留存约 10%–20%），机票和铁路取接近 0 到低个位数，保险可取较高比例但缺少可靠来源。活动抽成高于酒店，若不加约束，公式会系统性地偏向多塞付费活动。
- Connected Trip 的 low double-digit 占比给了搭售率的现实量级：即使是最大的平台，同一行程跨品类成交也只有一成出头；demo 中把 attach rate 设得明显高于这一水平需要说明理由。
- 中国《电子商务法》第十九条禁止把搭售设为默认同意，行程方案里附带的付费项目应由用户主动选择。

### Gaps
- 日本的铁路通票、交通卡、机场接送等在 OTA 上的佣金率没有查到。
- 机票、租车、保险的现行佣金没有审计或官方口径数字；Trip.com 的交通票务 GMV 未在摘录中披露，无法计算其票务 take rate。
- 打包产品（机 + 酒）的利润率以及各平台的品类 attach rate（除 Booking 的定性表述外）没有查到。
- GetYourGuide、Viator 没有公开的官方供应商费率表，数字来自个别运营商和行业媒体。

## 7. 可行性标尺：最小 learning-to-rank / 转化预测管线需要什么，一人能做到哪一步

### Takeaway
公开记录显示，用公开数据做出接近竞赛水平的酒店排序模型是个人或小团队量级的工作（Expedia ICDM 2013 上单个 GBM 的 NDCG@38 为 0.525，前五名集成为 0.531）；而让模型在真实流量上产生可信的预订增益需要大规模日志和线上实验（Airbnb 从 GBDT 到 DNN 用了约两年、17 亿训练样本对，简单神经网络上线时对预订无增益）。没有真实流量时，行业和学术界的标准简化是规则或 logit 效用排序、在用户排序基础上做有界 re-rank，以及用选择模型驱动的模拟用户做反事实评估。

### Cited Findings
- 【学术，KDD 2019】Airbnb 的演进路径：最初的搜索排序是"a manually crafted scoring function"；换成 GBDT 带来 Airbnb 历史上最大的预订增幅之一，随后增益饱和；转向神经网络"Two years after taking the first steps"才稳定，TensorFlow 模型 2017 年初开始上线；第一个简单 NN（32 个 ReLU 单隐层）相对 GBDT 预订持平；最终 DNN 用 17 亿训练样本对；作者的建议是起步阶段"don't be a hero"，并称迁移"is not a drop-in model replacement"— [arXiv:1810.09591](https://ar5iv.labs.arxiv.org/html/1810.09591)
- 【学术，二手摘要】Booking.com 约 150 个面向客户的 ML 应用的经验：离线指标与业务指标不对等，价值靠随机对照试验确认 — [The Morning Paper 摘要](https://blog.acolyer.org/2019/10/07/150-successful-machine-learning-models/)
- 【学术，2013】Expedia ICDM 2013 参赛队（私榜第 5，NDCG@38 = 0.53102）报告的单模型成绩（内部验证集）：仅 7 个特征的线性模型 0.51273；pairwise logistic regression 0.47；random forest 约 0.51–0.52；单个 GBM 0.52477；LambdaMART 0.51149；训练数据 9,917,530 行；他们用 10% 抽样做内部验证，并对正负样本做平衡采样以缩短树模型训练时间 — [arXiv:1311.7679](https://arxiv.org/pdf/1311.7679)
- 【课程项目】斯坦福 CS229 2013 年有多组学生用同一数据完成酒店排序课程项目 — [Rank hotels on Expedia.com to maximize purchases](https://cs229.stanford.edu/proj2013/KroshilinaKhantalMaini-RankHotelsOnExpediaToMaximizePurchases.pdf)；[Personalized Expedia Hotel Searches](https://cs229.stanford.edu/proj2013/XiaoJiangLi-PersonalizedExpediaHotelSearches.pdf)
- 【学术，2017】Expedia 的多目标 re-rank：在面向消费者的初始排序上做有约束的重排，对比对象是"business-rules-oriented baseline"，说明业务规则重排本身是生产中的常见基线 — [arXiv:1708.00651](https://arxiv.org/abs/1708.00651)
- 【学术】Greminger 用结构化搜索模型在离线数据上评估多种反事实排序（效用排序、Bottom-Up、按价格降序等）对收入和消费者福利的影响，全程不需要线上流量 — [arXiv:2210.16408](https://arxiv.org/html/2210.16408v5)
- 【学术】Ursu：Expedia 需要专门投放随机排序流量才能得到不带位置偏差的训练数据，这部分流量成交更少 — [Ursu, Marketing Science 2018](https://pubsonline.informs.org/doi/fpi/10.1287/mksc.2017.1072)
- 【开源】choice-learn 自带 Expedia 数据加载与预处理（过滤价格 10–1000 美元、入住不超过 14 晚、提前期不超过 365 天，补齐 38 个候选并加入不购买选项），支持 Conditional / Nested / Mixed Logit — [choice-learn 文档](https://artefactory.github.io/choice-learn/references/datasets/references_expedia/)；[JOSS 论文](https://joss.theoj.org/papers/10.21105/joss.06899.pdf)
- 【开源/学术】RecSim（Google）是可配置的推荐模拟平台，由用户模型、文档模型和 user-choice model 组成；作者明确说高保真模拟全部用户行为不是其目标，sim-to-real 迁移不保证 — [RecSim arXiv:1909.04847](https://arxiv.org/abs/1909.04847)；[Google Research blog](https://www.research.google/blog/recsim-a-configurable-simulation-platform-for-recommender-systems/)
- 【学术，CIKM 2023】生产系统多目标改动的线上增益量级：Fliggy MERIT 两周测试 CVR +1.50%；Fliggy 价格竞争力模型四周测试 CVR +4.9%、GMV +3.2% — [MERIT](https://dl.acm.org/doi/pdf/10.1145/3583780.3614964)；[Prices Do Matter](https://www.researchgate.net/publication/390545664_Prices_Do_Matter_Modeling_Price_Competitiveness_for_Online_Hotel_Industry)

### Inferences
- 一名开发者在 4–5 个月内可以可信地做到的部分：用 Expedia ICDM 2013 拟合预订概率模型（conditional logit 或 LightGBM/LambdaMART，公开成绩表明单模型即可接近竞赛前列）；外接一张带来源区间的佣金表得到收入项；在用户效用排序上做带上限的 re-rank（最大位移、Kendall tau 距离、评分门槛、每屏合作酒店占比任选）；用选择模型驱动的模拟用户比较"纯效用排序、收入最大化排序、带上限排序"三者的成交、收入和用户效用；输出披露标识和推荐理由。这些步骤每一项都有上面引用的公开先例。
- 不能可信声称的部分：真实转化率或收入提升（Booking 和 Airbnb 都强调离线指标与线上结果不对等，生产团队的改动通常只带来 1%–5% 的相对变化，且需要数周 A/B）；基于自有日志的 position bias 纠偏（需要随机流量）；对长期留存或信任的影响（本次没有找到可用的量化先例）。
- 因此"用这个分数影响线上酒店排序"在机制上可以做成一个确定性的 re-rank 层并演示，但它的效果证据只能是"在公开数据拟合的模拟用户上的反事实结果"，表述上应与真实线上效果分开。
- 模拟评估的固有局限是循环论证：模拟用户的选择模型与被评估的 P(预订) 模型若来自同一份数据和同一函数形式，排序自然显得更优。缓解办法是用不同模型族或不同数据子集分别拟合"评分用模型"和"模拟用户模型"，例如用 `random_bool=1` 子集拟合模拟用户、用其余数据拟合打分模型。
- 手设权重的 logit 效用并不寒酸：Airbnb 的起点就是手工评分函数，Expedia 论文的对照基线是业务规则；关键是把权重来源（数据拟合或文献 WTP 比值）写清楚。

### Gaps
- 各论文没有披露排序团队的人数和人月投入；Airbnb 只给出"约两年"的时间跨度。
- 没有找到"训练一个可用的酒店排序模型至少需要多少条日志"的经验阈值；只有 Expedia 竞赛（约 40 万次搜索、990 万行）这一可行实例。
- 没有找到专门评估"模拟用户结论与线上实验结论一致性"的旅行领域研究。
- 没有找到公开的对话式（LLM agent）酒店推荐场景下，把预订概率与佣金合成评分并做线上验证的案例。
