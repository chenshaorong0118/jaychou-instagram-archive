import Fuse from "fuse.js";
import OpenCC from "opencc-js/t2cn";
import "./style.css";

type ItemType = "post" | "story";

interface IndexItem {
  pk: string;
  item_type: ItemType;
  published_at_utc: string;
  published_at_taipei: string;
  repository: string;
  media_commit: string;
  thumbnail_commit: string;
  path: string;
  media_count: number;
  has_image: boolean;
  has_video: boolean;
  has_audio: boolean;
  thumbnail_path: string;
  metadata_shard: string;
}

interface SearchItem {
  pk: string;
  published_at_taipei: string;
  year_month: string;
  item_type: ItemType;
  caption: string | null;
  media_count: number;
  has_image: boolean;
  has_video: boolean;
  has_audio: boolean;
  search_text_simplified: string;
}

interface MediaAsset {
  type: "image" | "video" | "audio" | "poster" | "thumbnail";
  filename: string;
  mime_type: string;
}

interface MediaPosition {
  index: number;
  kind: "image" | "video" | "image_with_audio";
  assets: MediaAsset[];
}

interface MetadataItem {
  pk: string;
  item_type: ItemType;
  published_at_taipei: string;
  caption: string | null;
  text: string | null;
  repository: string;
  media_commit: string;
  path: string;
  media: MediaPosition[];
}

interface MetadataShard {
  schema_version: number;
  year_month: string;
  items: Record<string, MetadataItem>;
}

const WEEKDAYS = ["週日", "週一", "週二", "週三", "週四", "週五", "週六"];
const ICONS = {
  video: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z" /></svg>',
  audio: '<svg viewBox="0 0 24 24"><path d="M9 18V6l10-2v12M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm10-2a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /></svg>',
  multiple: '<svg viewBox="0 0 24 24"><path d="M8 8h12v12H8zM4 16V4h12" /></svg>',
};

const base = import.meta.env.BASE_URL;
const rawUrl = (repository: string, commit: string, path: string): string =>
  `https://raw.githubusercontent.com/${repository}/${commit}/${path}`;
const normalize = (value: string): string =>
  value.normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, " ").trim();
const traditionalToSimplified = OpenCC.Converter({ from: "t", to: "cn" });

const gallery = requiredElement<HTMLDivElement>("gallery");
const status = requiredElement<HTMLParagraphElement>("status");
const searchInput = requiredElement<HTMLInputElement>("search-input");
const monthFilter = requiredElement<HTMLSelectElement>("month-filter");
const mediaFilter = requiredElement<HTMLSelectElement>("media-filter");
const dialog = requiredElement<HTMLDialogElement>("lightbox");
const stage = requiredElement<HTMLDivElement>("lightbox-stage");
const progress = requiredElement<HTMLDivElement>("lightbox-progress");
const lightboxKicker = requiredElement<HTMLSpanElement>("lightbox-kicker");
const lightboxTitle = requiredElement<HTMLHeadingElement>("lightbox-title");
const lightboxTime = requiredElement<HTMLParagraphElement>("lightbox-time");
const lightboxCaption = requiredElement<HTMLParagraphElement>("lightbox-caption");
const lightboxPosition = requiredElement<HTMLElement>("lightbox-position");
const lightboxPk = requiredElement<HTMLElement>("lightbox-pk");
const copyLink = requiredElement<HTMLButtonElement>("copy-link");
const openOriginal = requiredElement<HTMLAnchorElement>("open-original");
const previousButton = document.querySelector<HTMLButtonElement>(".nav--previous");
const nextButton = document.querySelector<HTMLButtonElement>(".nav--next");

let items: IndexItem[] = [];
let visible: IndexItem[] = [];
let searchItems: SearchItem[] = [];
let typeValue = "";
let currentItem: IndexItem | null = null;
let currentMetadata: MetadataItem | null = null;
let currentMediaIndex = 0;
let openToken = 0;
const metadataCache = new Map<string, Promise<MetadataShard>>();
let lazyObserver: IntersectionObserver | null = null;

function requiredElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing element: ${id}`);
  return element as T;
}

async function fetchText(path: string): Promise<string> {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.text();
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json() as Promise<T>;
}

/** Parts of a Taipei timestamp such as 2026-10-08T01:18:01+08:00, read as written. */
function taipeiParts(value: string) {
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  return {
    year,
    month,
    day,
    time: value.slice(11, 16),
    weekday: WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()] ?? "",
  };
}

function monthLabel(yearMonth: string): string {
  return `${yearMonth.slice(0, 4)} 年 ${Number(yearMonth.slice(5, 7))} 月`;
}

function readView(): string {
  try {
    return localStorage.getItem("archive-view") === "masonry" ? "masonry" : "grid";
  } catch {
    return "grid";
  }
}

async function loadData(): Promise<void> {
  const [itemsText, searchPayload] = await Promise.all([
    fetchText("index/items.jsonl"),
    fetchJson<{ schema_version: number; items: SearchItem[] }>("index/search-items.json"),
  ]);
  items = itemsText
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as IndexItem)
    .sort((a, b) =>
      `${b.published_at_taipei}:${b.pk}`.localeCompare(`${a.published_at_taipei}:${a.pk}`),
    );
  searchItems = searchPayload.items;
  populateStats();
  populateMonths();
  render();
  const selected = new URL(window.location.href).searchParams.get("item");
  if (selected) {
    const item = items.find((candidate) => candidate.pk === selected);
    if (item) await openItem(item, 0, false);
  }
}

function populateStats(): void {
  const set = (id: string, value: string) => {
    requiredElement<HTMLElement>(id).textContent = value;
  };
  set("stat-total", String(items.length));
  set("stat-stories", String(items.filter((item) => item.item_type === "story").length));
  set("stat-posts", String(items.filter((item) => item.item_type === "post").length));
  const latest = items[0];
  if (latest) {
    const parts = taipeiParts(latest.published_at_taipei);
    set("stat-latest", `${parts.month}/${parts.day}`);
  }
}

function populateMonths(): void {
  const months = [...new Set(items.map((item) => item.published_at_taipei.slice(0, 7)))];
  for (const month of months.sort().reverse()) {
    const option = document.createElement("option");
    option.value = month;
    option.textContent = monthLabel(month);
    monthFilter.append(option);
  }
}

function matchedPks(): Set<string> | null {
  const query = normalize(searchInput.value);
  if (!query) return null;
  const simplifiedQuery = traditionalToSimplified(query);
  const fuse = new Fuse(searchItems, {
    keys: [
      { name: "caption", weight: 0.55 },
      { name: "search_text_simplified", weight: 0.45 },
      { name: "pk", weight: 0.2 },
    ],
    threshold: 0.32,
    ignoreLocation: true,
    useTokenSearch: true,
  });
  return new Set(fuse.search(simplifiedQuery).map((result) => result.item.pk));
}

function filteredItems(): IndexItem[] {
  const matches = matchedPks();
  return items.filter((item) => {
    if (matches && !matches.has(item.pk)) return false;
    if (monthFilter.value && !item.published_at_taipei.startsWith(monthFilter.value)) return false;
    if (typeValue && item.item_type !== typeValue) return false;
    if (mediaFilter.value === "image" && !item.has_image) return false;
    if (mediaFilter.value === "video" && !item.has_video) return false;
    if (mediaFilter.value === "audio" && !item.has_audio) return false;
    return true;
  });
}

function render(): void {
  lazyObserver?.disconnect();
  gallery.replaceChildren();
  visible = filteredItems();
  status.textContent = visible.length ? "" : "沒有符合條件的項目。";
  const groups = new Map<string, IndexItem[]>();
  for (const item of visible) {
    const month = item.published_at_taipei.slice(0, 7);
    groups.set(month, [...(groups.get(month) ?? []), item]);
  }
  for (const [month, group] of groups) {
    const section = document.createElement("section");
    section.className = "month";
    const heading = document.createElement("div");
    heading.className = "month__heading";
    const title = document.createElement("h2");
    title.textContent = monthLabel(month);
    const count = document.createElement("span");
    count.textContent = `${group.length} 則`;
    heading.append(title, count);
    const cards = document.createElement("div");
    cards.className = "month__cards";
    for (const item of group) cards.append(createCard(item));
    section.append(heading, cards);
    gallery.append(section);
  }
  installLazyLoading();
}

function createCard(item: IndexItem): HTMLButtonElement {
  const parts = taipeiParts(item.published_at_taipei);
  const card = document.createElement("button");
  card.type = "button";
  card.className = "card";
  card.dataset.pk = item.pk;
  card.setAttribute(
    "aria-label",
    `${item.item_type === "story" ? "Story" : "Post"} ${parts.month} 月 ${parts.day} 日 ${parts.time}`,
  );
  const image = document.createElement("img");
  image.alt = "";
  image.decoding = "async";
  image.dataset.src = rawUrl(item.repository, item.thumbnail_commit, item.thumbnail_path);
  image.addEventListener("load", () => card.classList.add("is-loaded"), { once: true });
  image.addEventListener("error", () => card.classList.add("is-loaded"), { once: true });
  // Most items are Stories; only Posts get a label so it stands out.
  const type = document.createElement("span");
  type.className = "card__type";
  type.textContent = "Post";
  type.hidden = item.item_type !== "post";
  const icons = document.createElement("span");
  icons.className = "card__icons";
  const addIcon = (svg: string, label: string) => {
    const icon = document.createElement("span");
    icon.innerHTML = svg;
    icon.title = label;
    icons.append(icon);
  };
  if (item.media_count > 1) addIcon(ICONS.multiple, `${item.media_count} 個媒體`);
  if (item.has_video) addIcon(ICONS.video, "影片");
  if (item.has_audio) addIcon(ICONS.audio, "有聲音");
  const date = document.createElement("span");
  date.className = "card__date";
  date.textContent = `${parts.month}/${parts.day} ${parts.time}`;
  card.append(image, type, icons, date);
  card.addEventListener("click", () => void openItem(item));
  return card;
}

function installLazyLoading(): void {
  lazyObserver = new IntersectionObserver(
    (entries, observer) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const image = entry.target as HTMLImageElement;
        const source = image.dataset.src;
        if (source) image.src = source;
        image.removeAttribute("data-src");
        observer.unobserve(image);
      }
    },
    { rootMargin: "600px 0px" },
  );
  for (const image of gallery.querySelectorAll<HTMLImageElement>("img[data-src]")) {
    lazyObserver.observe(image);
  }
}

function loadMetadataShard(path: string): Promise<MetadataShard> {
  const existing = metadataCache.get(path);
  if (existing) return existing;
  const pending = fetchJson<MetadataShard>(path);
  pending.catch(() => metadataCache.delete(path));
  metadataCache.set(path, pending);
  return pending;
}

async function openItem(item: IndexItem, mediaIndex = 0, updateHistory = true): Promise<void> {
  const token = ++openToken;
  const shard = await loadMetadataShard(item.metadata_shard);
  if (token !== openToken) return;
  const metadata = shard.items[item.pk];
  if (!metadata) throw new Error(`Metadata not found: ${item.pk}`);
  currentItem = item;
  currentMetadata = metadata;
  currentMediaIndex = Math.min(Math.max(mediaIndex, 0), metadata.media.length - 1);
  const parts = taipeiParts(metadata.published_at_taipei);
  lightboxKicker.textContent = metadata.item_type === "story" ? "STORY" : "POST";
  lightboxTitle.textContent = `${parts.year} 年 ${parts.month} 月 ${parts.day} 日 ${parts.weekday}`;
  lightboxTime.textContent = `${parts.time} 台北時間`;
  const text = metadata.caption || metadata.text;
  lightboxCaption.textContent = text || "沒有文字內容";
  lightboxCaption.classList.toggle("is-empty", !text);
  lightboxPk.textContent = metadata.pk;
  renderMedia();
  if (!dialog.open) dialog.showModal();
  if (updateHistory) updateItemUrl(item.pk);
}

function assetUrl(metadata: MetadataItem, asset: MediaAsset): string {
  return rawUrl(metadata.repository, metadata.media_commit, `${metadata.path}/${asset.filename}`);
}

function renderMedia(): void {
  stage.replaceChildren();
  progress.replaceChildren();
  if (!currentMetadata) return;
  const position = currentMetadata.media[currentMediaIndex];
  if (!position) return;
  const find = (type: MediaAsset["type"]) => position.assets.find((asset) => asset.type === type);
  const imageAsset = find("image");
  const videoAsset = find("video");
  const posterAsset = find("poster") ?? find("thumbnail");
  const alt = currentMetadata.caption || currentMetadata.text || `媒體 ${position.index}`;
  if (videoAsset) {
    const video = document.createElement("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.src = assetUrl(currentMetadata, videoAsset);
    if (posterAsset && !imageAsset) video.poster = assetUrl(currentMetadata, posterAsset);
    if (imageAsset) {
      const image = document.createElement("img");
      image.src = assetUrl(currentMetadata, imageAsset);
      image.alt = alt;
      stage.append(image);
    }
    stage.append(video);
    void video.play().catch(() => undefined);
    openOriginal.href = video.src;
  } else if (imageAsset) {
    const image = document.createElement("img");
    image.src = assetUrl(currentMetadata, imageAsset);
    image.alt = alt;
    stage.append(image);
    openOriginal.href = image.src;
  }
  const total = currentMetadata.media.length;
  lightboxPosition.textContent = `${position.index} / ${total}`;
  if (total > 1) {
    for (let index = 0; index < total; index += 1) {
      const bar = document.createElement("span");
      bar.classList.toggle("is-active", index <= currentMediaIndex);
      progress.append(bar);
    }
  }
  const itemIndex = currentItem ? visible.indexOf(currentItem) : -1;
  if (previousButton) previousButton.disabled = currentMediaIndex === 0 && itemIndex <= 0;
  if (nextButton) {
    nextButton.disabled = currentMediaIndex >= total - 1 && (itemIndex < 0 || itemIndex >= visible.length - 1);
  }
}

/** Step through media, then continue into the neighbouring item like a Story viewer. */
function step(direction: 1 | -1): void {
  if (!currentMetadata || !currentItem) return;
  const target = currentMediaIndex + direction;
  if (target >= 0 && target < currentMetadata.media.length) {
    currentMediaIndex = target;
    renderMedia();
    return;
  }
  const itemIndex = visible.indexOf(currentItem);
  const neighbour = itemIndex < 0 ? undefined : visible[itemIndex + direction];
  if (neighbour) void openItem(neighbour, direction === 1 ? 0 : neighbour.media_count - 1);
}

function updateItemUrl(pk: string | null): void {
  const url = new URL(window.location.href);
  if (pk) url.searchParams.set("item", pk);
  else url.searchParams.delete("item");
  window.history.replaceState({}, "", url);
}

document.querySelector<HTMLButtonElement>(".close")?.addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
dialog.addEventListener("close", () => {
  openToken += 1;
  stage.replaceChildren();
  currentItem = null;
  currentMetadata = null;
  updateItemUrl(null);
});
dialog.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
  // Arrows always move between media/items, even when the video has focus.
  event.preventDefault();
  step(event.key === "ArrowRight" ? 1 : -1);
});
let touchStartX: number | null = null;
stage.addEventListener("touchstart", (event) => {
  touchStartX = event.touches[0]?.clientX ?? null;
}, { passive: true });
stage.addEventListener("touchend", (event) => {
  const endX = event.changedTouches[0]?.clientX;
  if (touchStartX !== null && endX !== undefined && Math.abs(endX - touchStartX) > 50) {
    step(endX < touchStartX ? 1 : -1);
  }
  touchStartX = null;
});
previousButton?.addEventListener("click", () => step(-1));
nextButton?.addEventListener("click", () => step(1));
copyLink.addEventListener("click", async () => {
  await navigator.clipboard.writeText(window.location.href);
  copyLink.textContent = "已複製";
  window.setTimeout(() => {
    copyLink.textContent = "複製連結";
  }, 1200);
});

searchInput.addEventListener("input", render);
monthFilter.addEventListener("change", render);
mediaFilter.addEventListener("change", render);

document.querySelectorAll<HTMLButtonElement>("[data-type]").forEach((button) => {
  button.addEventListener("click", () => {
    typeValue = button.dataset.type ?? "";
    document
      .querySelectorAll<HTMLButtonElement>("[data-type]")
      .forEach((candidate) => candidate.setAttribute("aria-pressed", String(candidate === button)));
    render();
  });
});

function applyView(view: string): void {
  gallery.className = `gallery gallery--${view}`;
  document
    .querySelectorAll<HTMLButtonElement>("[data-view]")
    .forEach((candidate) =>
      candidate.setAttribute("aria-pressed", String(candidate.dataset.view === view)),
    );
}

document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view ?? "grid";
    applyView(view);
    try {
      localStorage.setItem("archive-view", view);
    } catch {
      // Storage may be unavailable (private mode); the view still switches.
    }
  });
});

applyView(readView());
void loadData().catch((error: unknown) => {
  console.error(error);
  status.textContent = "索引載入失敗，請稍後重試。";
});
