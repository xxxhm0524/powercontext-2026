const DEFAULT_MAX_CHARS = 420;
const DEFAULT_OVERLAP = 60;

/** FNV-1a: short stable identifier for a piece of text. */
export function hashString(value) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function splitLongSentence(sentence, maxChars, overlap) {
  const pieces = [];
  let start = 0;
  while (start < sentence.length) {
    const end = Math.min(sentence.length, start + maxChars);
    pieces.push(sentence.slice(start, end));
    if (end === sentence.length) break;
    start = Math.max(end - overlap, start + 1);
  }
  return pieces;
}

/**
 * Paragraph/sentence-aware chunking with a character budget and overlap.
 * Chinese text has no spaces, so a character budget is more reliable than words.
 */
export function chunkText(text, options = {}) {
  const maxChars = options.maxChars || DEFAULT_MAX_CHARS;
  const overlap = Math.min(options.overlap ?? DEFAULT_OVERLAP, Math.floor(maxChars / 3));
  const normalized = String(text || "").replace(/\r\n?/g, "\n").trim();
  if (!normalized) return [];

  const paragraphs = normalized.split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
  const sentences = [];
  for (const paragraph of paragraphs) {
    const parts = paragraph.split(/(?<=[。！？!?；;])\s*/).map((item) => item.trim()).filter(Boolean);
    for (const part of parts) {
      if (part.length > maxChars) sentences.push(...splitLongSentence(part, maxChars, overlap));
      else sentences.push(part);
    }
  }

  const chunks = [];
  let current = "";
  let currentStart = 0;
  let cursor = 0;
  for (const sentence of sentences) {
    const nextLength = current ? current.length + sentence.length : sentence.length;
    if (nextLength > maxChars && current) {
      chunks.push({ text: current, start: currentStart, end: currentStart + current.length });
      const tail = current.slice(Math.max(0, current.length - overlap));
      currentStart = currentStart + current.length - tail.length;
      current = `${tail}${sentence}`;
    } else {
      if (!current) currentStart = cursor;
      current += sentence;
    }
    cursor += sentence.length;
  }
  if (current) chunks.push({ text: current, start: currentStart, end: currentStart + current.length });
  return chunks.filter((chunk) => chunk.text.trim().length > 0);
}

export function sourceSlug(name) {
  return String(name || "document")
    .replace(/\.[^.]+$/, "")
    .replace(/[^a-zA-Z0-9\u4e00-\u9fa5_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "document";
}

/** Convert one file's text into deterministic chunk records. */
export function buildFileChunks(fileName, text) {
  const slug = sourceSlug(fileName);
  const isJsonl = /\.jsonl?$/i.test(fileName);
  const isCsv = /\.csv$/i.test(fileName);
  const lines = isJsonl || isCsv
    ? text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    : null;
  const units = lines
    ? lines.map((line, index) => ({ text: line, title: `${fileName} · 第 ${index + 1} 行` }))
    : chunkText(text).map((chunk, index) => ({ text: chunk.text, title: `${fileName} · 片段 ${index + 1}` }));

  return units.map((unit, index) => {
    const id = `f_${slug}_${hashString(`${fileName}:${index}:${unit.text}`)}`;
    return {
      id,
      text: unit.text,
      metadata: {
        source: fileName,
        title: unit.title,
        category: "文件导入",
        chunkIndex: index,
        chunkCount: units.length,
        chars: unit.text.length,
      },
    };
  });
}

export function buildSampleChunks(documents) {
  return documents.map((doc) => ({
    id: `s_${doc.id}_${hashString(`${doc.title}:${doc.text}`)}`,
    text: `${doc.title}\n${doc.text}`,
    metadata: {
      source: "示例语料",
      title: doc.title,
      category: doc.category,
      chunkIndex: 0,
      chunkCount: 1,
      chars: doc.text.length,
    },
  }));
}

export async function readTextFile(file) {
  if (file.size > 8 * 1024 * 1024) {
    throw new Error(`${file.name} 超过 8 MB，请拆分后再导入`);
  }
  const lower = file.name.toLowerCase();
  if (/\.(png|jpe?g|gif|webp|pdf|docx?|xlsx?|pptx?|zip|gz|mp4|mov)$/.test(lower)) {
    throw new Error(`${file.name} 不是纯文本文件。本题基础版支持 .txt / .md / .csv / .jsonl / .log`);
  }
  return file.text();
}
