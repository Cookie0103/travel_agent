import assert from "node:assert/strict";
import { test } from "node:test";
import {
  moreTile,
  safeRakutenTravelUrl,
  scrollButtons,
} from "../src/lib/hotel-more.ts";

const ok = "https://travel.rakuten.co.jp/yado/okinawa/naha.html";

test("safe URL accepts https Rakuten Travel host and subdomains", () => {
  assert.equal(safeRakutenTravelUrl(ok), ok);
  assert.equal(
    safeRakutenTravelUrl("https://www.travel.rakuten.co.jp/x"),
    "https://www.travel.rakuten.co.jp/x",
  );
});

test("unsafe or missing URLs are rejected", () => {
  for (const bad of [
    "http://travel.rakuten.co.jp/x",
    "https://travel.rakuten.co.jp.evil.com/x",
    "https://eviltravel.rakuten.co.jp.evil.com/",
    "https://nottravel.rakuten.co.jp/x",
    "https://rakuten.co.jp/x",
    "javascript:alert(1)",
    "https://user:pw@travel.rakuten.co.jp/x",
    "https://travel.rakuten.co.jp:8443/x",
    "https://travel.rakuten.co.jp./x",
    "https://xn--travel-rakuten-co-jp-9x0f.com/",
    "https://travel.rakuten.co.jp@evil.com/",
    "https://travel.rakuten.cо.jp/x",
    "//travel.rakuten.co.jp/",
    "not a url",
    "",
    null,
    undefined,
  ])
    assert.equal(safeRakutenTravelUrl(bad), undefined, String(bad));
});

test("uppercase host is normalised to the allowed lowercase host", () => {
  assert.equal(
    safeRakutenTravelUrl("HTTPS://TRAVEL.RAKUTEN.CO.JP/x"),
    "https://travel.rakuten.co.jp/x",
  );
});

test("backslash form is normalised by the URL parser to the real allowed host", () => {
  assert.equal(
    safeRakutenTravelUrl("https:\\\\travel.rakuten.co.jp\\x"),
    "https://travel.rakuten.co.jp/x",
  );
});

test("tile text is honest per scope and includes the total only when known", () => {
  const dest = moreTile({
    more_url: ok,
    more_url_scope: "destination",
    total_found: 187,
  });
  assert.equal(
    dest?.title,
    "在乐天查看更多酒店（本次搜索范围内有空房 187 家）",
  );
  assert.equal(
    dest?.note,
    "将打开乐天的目的地酒店页，入住日期和人数需要在乐天重新选择。",
  );
  assert.match(dest?.note ?? "", /重新选择/);
  const search = moreTile({
    more_url: ok,
    more_url_scope: "search",
    total_found: null,
  });
  assert.equal(search?.title, "在乐天查看更多酒店");
  assert.equal(search?.note, "将打开乐天的搜索结果页。");
  assert.equal(
    moreTile({ more_url: ok, more_url_scope: "search", total_found: 12 })
      ?.title,
    "在乐天查看更多酒店（本次搜索范围内有空房 12 家）",
  );
  assert.doesNotMatch(search?.note ?? "", /重新选择/);
});

test("tile tolerates absent fields and never appears without a safe link", () => {
  assert.equal(moreTile({}), undefined);
  assert.equal(
    moreTile({ more_url: "http://travel.rakuten.co.jp/", total_found: 5 }),
    undefined,
  );
  const bare = moreTile({ more_url: ok });
  assert.equal(bare?.title, "在乐天查看更多酒店");
  assert.match(bare?.note ?? "", /重新选择/);
  assert.equal(
    moreTile({ more_url: ok, total_found: 0 })?.title,
    "在乐天查看更多酒店",
  );
});

test("scroll buttons follow position and hide without overflow", () => {
  assert.deepEqual(scrollButtons(0, 500, 500), {
    overflow: false,
    canPrev: false,
    canNext: false,
  });
  assert.deepEqual(scrollButtons(0, 300, 900), {
    overflow: true,
    canPrev: false,
    canNext: true,
  });
  assert.deepEqual(scrollButtons(300, 300, 900), {
    overflow: true,
    canPrev: true,
    canNext: true,
  });
  assert.deepEqual(scrollButtons(599.6, 300, 900), {
    overflow: true,
    canPrev: true,
    canNext: false,
  });
});
