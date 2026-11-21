/** Turn pasted text or a CSV file into answers for a batch check. */

export interface BatchInput {
  question?: string;
  answer: string;
}

export const MAX_BATCH = 20;

/**
 * Answers separated by a line holding only `---`. A block whose first line
 * starts with `Q:` uses that line as the question.
 */
export function parseBatchText(text: string): BatchInput[] {
  return text
    .split(/^\s*-{3,}\s*$/m)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const [first, ...rest] = block.split("\n");
      const match = /^q:\s*(.+)$/i.exec(first.trim());
      if (match && rest.join("\n").trim()) {
        return { question: match[1].trim(), answer: rest.join("\n").trim() };
      }
      return { answer: block };
    });
}

/** Split CSV text into rows, honouring quoted fields with commas, quotes and newlines. */
export function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((cells) => cells.some((cell) => cell.trim()));
}

/**
 * Read a CSV with an `answer` column and an optional `question` column. Without a
 * header row naming `answer`, the last column is the answer and an earlier one the question.
 */
export function parseBatchCsv(text: string): BatchInput[] {
  const rows = parseCsvRows(text.replace(/^\uFEFF/, ""));
  if (rows.length === 0) return [];
  const header = rows[0].map((cell) => cell.trim().toLowerCase());
  let answerAt = header.indexOf("answer");
  let questionAt = header.indexOf("question");
  let body = rows.slice(1);
  if (answerAt === -1) {
    body = rows;
    answerAt = rows[0].length - 1;
    questionAt = rows[0].length > 1 ? 0 : -1;
  }
  return body
    .map((cells) => ({
      question: questionAt >= 0 ? cells[questionAt]?.trim() || undefined : undefined,
      answer: (cells[answerAt] ?? "").trim(),
    }))
    .filter((item) => item.answer);
}
