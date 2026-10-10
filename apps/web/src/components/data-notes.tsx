/** Data attribution kept reachable but out of the chat: hover, click or focus opens it. */
"use client";
import { HoverPopover } from "./ui/hover-popover";

export function DataNotes() {
  return (
    <HoverPopover label="数据说明">
      <div className="grid gap-3 [&_strong]:mr-2">
        <p>
          <strong>景点与路线</strong>
          <a
            href="https://developers.google.com/maps/documentation"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google Maps Platform
          </a>
          （Places / Routes / Geocoding）
        </p>
        <p>
          <strong>酒店</strong>
          <a
            href="https://webservice.rakuten.co.jp/"
            target="_blank"
            rel="noopener noreferrer"
          >
            乐天トラベル（Rakuten Web Service）
          </a>
          ，报价以供应商页面为准
        </p>
        <p>
          <strong>天气</strong>
          <a
            href="https://open-meteo.com/en/docs"
            target="_blank"
            rel="noopener noreferrer"
          >
            Open-Meteo.com
          </a>
          （
          <a
            href="https://creativecommons.org/licenses/by/4.0/"
            target="_blank"
            rel="noopener noreferrer"
          >
            CC BY 4.0
          </a>
          ）
        </p>
      </div>
    </HoverPopover>
  );
}
