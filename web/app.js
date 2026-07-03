const state = {
  puzzles: [],
  filtered: [],
  index: 0,
  board: {},
  selected: null,
  ply: 0,
  orientation: "w",
  solved: false,
};

const files = ["a", "b", "c", "d", "e", "f", "g", "h"];
const hiddenTags = new Set(["standard-like", "trivial-recapture", "trivial-capture", "check-evasion"]);
const boardEl = document.getElementById("board");
const counterEl = document.getElementById("counter");
const titleEl = document.getElementById("title");
const statusEl = document.getElementById("status");
const sourceEl = document.getElementById("source");
const solutionEl = document.getElementById("solution");
const lineEl = document.getElementById("line");
const detailsEl = document.getElementById("details");

const controls = {
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  reset: document.getElementById("reset"),
  random: document.getElementById("random"),
  reveal: document.getElementById("reveal"),
  theme: document.getElementById("theme"),
  analysis: document.getElementById("analysis"),
  showHidden: document.getElementById("show-hidden"),
  hiddenOptions: document.getElementById("hidden-options"),
  showCheck: document.getElementById("show-check"),
  showRecapture: document.getElementById("show-recapture"),
  phase: document.getElementById("phase-filter"),
  motif: document.getElementById("motif-filter"),
  length: document.getElementById("length-filter"),
  categoryToggle: document.getElementById("category-toggle"),
  categoryOptions: document.getElementById("category-options"),
  boardTheme: document.getElementById("board-theme"),
};

async function boot() {
  applySavedTheme();
  applySavedBoardTheme();
  try {
    const response = await fetch("public/puzzles.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.puzzles = (payload.puzzles || []).map(enrichPuzzle);
    populateCategoryFilters();
    bindControls();
    applyFilters();
  } catch (error) {
    setStatus(`Could not load puzzles: ${error.message}`, "bad");
  }
}

function bindControls() {
  controls.prev.addEventListener("click", () => gotoPuzzle(state.index - 1));
  controls.next.addEventListener("click", () => gotoPuzzle(state.index + 1));
  controls.reset.addEventListener("click", resetPuzzle);
  controls.random.addEventListener("click", () => gotoPuzzle(Math.floor(Math.random() * state.filtered.length)));
  controls.reveal.addEventListener("click", revealSolution);
  controls.theme.addEventListener("click", toggleTheme);
  controls.categoryToggle.addEventListener("click", toggleCategoryFilters);
  controls.boardTheme.addEventListener("change", () => applyBoardTheme(controls.boardTheme.value));
  for (const input of [controls.showHidden, controls.showCheck, controls.showRecapture, controls.phase, controls.motif, controls.length]) {
    input.addEventListener("change", applyFilters);
  }
}

function enrichPuzzle(puzzle) {
  const categories = puzzle.categories || {};
  return {
    ...puzzle,
    categories: {
      phase: categories.phase || inferPhase(puzzle),
      motifs: categories.motifs || inferMotifs(puzzle),
      length: categories.length || inferLength(puzzle),
    },
  };
}

function populateCategoryFilters() {
  fillSelect(controls.phase, [...new Set(state.puzzles.map((p) => p.categories.phase).filter(Boolean))], ["opening", "middlegame", "endgame"]);
  fillSelect(controls.motif, [...new Set(state.puzzles.flatMap((p) => p.categories.motifs || []))]);
  fillSelect(controls.length, [...new Set(state.puzzles.map((p) => p.categories.length).filter(Boolean))], ["one-move", "medium", "long"]);
}

function fillSelect(select, values, preferred = []) {
  const current = select.value;
  const ordered = [...preferred.filter((value) => values.includes(value)), ...values.filter((value) => !preferred.includes(value)).sort()];
  select.innerHTML = '<option value="">All</option>';
  for (const value of ordered) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelText(value);
    select.appendChild(option);
  }
  select.value = ordered.includes(current) ? current : "";
}

function applyFilters() {
  controls.hiddenOptions.classList.toggle("hidden", !controls.showHidden.checked);
  state.filtered = state.puzzles.filter((puzzle) => {
    const tags = new Set(puzzle.tags || []);
    const motifs = new Set(puzzle.categories.motifs || []);
    if (!controls.showHidden.checked && puzzle.hidden_by_default) return false;
    if (controls.showHidden.checked && !controls.showCheck.checked && tags.has("check-evasion")) return false;
    if (controls.showHidden.checked && !controls.showRecapture.checked && tags.has("trivial-recapture")) return false;
    if (controls.phase.value && puzzle.categories.phase !== controls.phase.value) return false;
    if (controls.motif.value && !motifs.has(controls.motif.value)) return false;
    if (controls.length.value && puzzle.categories.length !== controls.length.value) return false;
    return true;
  });
  state.index = Math.min(state.index, Math.max(0, state.filtered.length - 1));
  resetPuzzle();
}

function currentPuzzle() {
  return state.filtered[state.index];
}

function gotoPuzzle(index) {
  if (!state.filtered.length) return;
  state.index = (index + state.filtered.length) % state.filtered.length;
  resetPuzzle();
}

function resetPuzzle() {
  const puzzle = currentPuzzle();
  if (!puzzle) {
    boardEl.innerHTML = "";
    counterEl.textContent = "0 / 0";
    titleEl.textContent = "No puzzles";
    sourceEl.textContent = "";
    solutionEl.classList.add("hidden");
    controls.analysis.classList.add("hidden");
    setStatus("No puzzles match the current filters.", "bad");
    return;
  }
  state.board = parseFenBoard(puzzle.fen);
  state.orientation = puzzle.side || sideFromFen(puzzle.fen) || "w";
  state.selected = null;
  state.ply = 0;
  state.solved = false;
  solutionEl.classList.add("hidden");
  controls.analysis.classList.add("hidden");
  counterEl.textContent = `${state.index + 1} / ${state.filtered.length}`;
  titleEl.textContent = `${puzzle.side === "b" ? "Black" : "White"} to move`;
  sourceEl.textContent = sourceText(puzzle);
  lineEl.textContent = "";
  detailsEl.textContent = "";
  setStatus("Find the only move.");
  renderBoard();
}

function parseFenBoard(fen) {
  const placement = (fen || "").split(/\s+/)[0] || "8/8/8/8/8/8/8/8";
  const board = {};
  const ranks = placement.split("/");
  for (let rankIndex = 0; rankIndex < 8; rankIndex++) {
    let fileIndex = 0;
    for (const char of ranks[rankIndex] || "") {
      if (/\d/.test(char)) {
        fileIndex += Number(char);
      } else {
        const square = `${files[fileIndex]}${8 - rankIndex}`;
        board[square] = char;
        fileIndex += 1;
      }
    }
  }
  return board;
}

function sideFromFen(fen) {
  return (fen || "").split(/\s+/)[1];
}

function renderBoard() {
  boardEl.innerHTML = "";
  const ranks = state.orientation === "b" ? [1,2,3,4,5,6,7,8] : [8,7,6,5,4,3,2,1];
  const visibleFiles = state.orientation === "b" ? [...files].reverse() : files;
  for (const rank of ranks) {
    for (const file of visibleFiles) {
      const square = `${file}${rank}`;
      const button = document.createElement("button");
      button.className = `square ${squareColor(square)}`;
      if (state.selected === square) button.classList.add("selected");
      button.dataset.square = square;
      button.addEventListener("click", () => onSquare(square));
      const piece = state.board[square];
      if (piece) button.appendChild(pieceImage(piece));
      if ((state.orientation === "w" && (file === "a" || rank === 1)) || (state.orientation === "b" && (file === "h" || rank === 8))) {
        const coord = document.createElement("span");
        coord.className = "coord";
        coord.textContent = square;
        button.appendChild(coord);
      }
      boardEl.appendChild(button);
    }
  }
}

function squareColor(square) {
  const file = files.indexOf(square[0]) + 1;
  const rank = Number(square[1]);
  return (file + rank) % 2 === 0 ? "dark" : "light";
}

function pieceImage(piece) {
  const img = document.createElement("img");
  img.className = "piece";
  const color = piece === piece.toUpperCase() ? "w" : "b";
  img.src = `assets/pieces/${color}${piece.toUpperCase()}.svg`;
  img.alt = `${color}${piece.toUpperCase()}`;
  img.onerror = () => {
    const fallback = document.createElement("span");
    fallback.className = "piece-text";
    fallback.textContent = piece;
    img.replaceWith(fallback);
  };
  return img;
}

function onSquare(square) {
  if (state.solved) return;
  if (!state.selected) {
    if (!state.board[square]) return;
    state.selected = square;
    renderBoard();
    return;
  }
  if (state.selected === square) {
    state.selected = null;
    renderBoard();
    return;
  }
  tryUserMove(state.selected, square);
}

function tryUserMove(from, to) {
  const puzzle = currentPuzzle();
  const expected = (puzzle.solution || [])[state.ply];
  state.selected = null;
  if (!expected) return;
  const userPrefix = `${from}${to}`;
  if (!expected.startsWith(userPrefix)) {
    setStatus("That is not the tactic move.", "bad");
    renderBoard();
    return;
  }
  applyMove(expected);
  state.ply += 1;
  setStatus("Correct.", "good");
  renderBoard();
  setTimeout(autoReplies, 250);
}

function autoReplies() {
  const puzzle = currentPuzzle();
  if (!puzzle) return;
  const line = puzzle.solution || [];
  if (state.ply >= line.length) {
    markSolved();
    return;
  }
  if (state.ply % 2 === 1) {
    applyMove(line[state.ply]);
    state.ply += 1;
    renderBoard();
    if (state.ply >= line.length) {
      markSolved();
    } else {
      setStatus("Continue the line.");
    }
  }
}

function markSolved() {
  state.solved = true;
  setStatus("Solved.", "good");
  showAnalysisLink();
}

function applyMove(uci) {
  const from = uci.slice(0, 2);
  const to = uci.slice(2, 4);
  const suffix = uci.length > 4 ? uci[4].toLowerCase() : "";
  const piece = state.board[from];
  if (!piece) return;

  const castle = castleMove(from, to, piece, suffix);
  if (castle) {
    performCastle(castle, piece, suffix);
    return;
  }

  delete state.board[from];
  state.board[to] = promotedPiece(piece, to, suffix);
  if (isGateSuffix(suffix, from, piece, to)) {
    state.board[from] = piece === piece.toUpperCase() ? suffix.toUpperCase() : suffix;
  }
}

function castleMove(from, to, piece, suffix) {
  const white = piece === piece.toUpperCase();
  if (piece.toUpperCase() !== "K" && !rookCastleEncoding(from, to, white)) return null;
  const table = {
    e1g1: ["e1", "g1", "h1", "f1", "e1"],
    h1e1: ["e1", "g1", "h1", "f1", "h1"],
    e1c1: ["e1", "c1", "a1", "d1", "e1"],
    a1e1: ["e1", "c1", "a1", "d1", "a1"],
    e8g8: ["e8", "g8", "h8", "f8", "e8"],
    h8e8: ["e8", "g8", "h8", "f8", "h8"],
    e8c8: ["e8", "c8", "a8", "d8", "e8"],
    a8e8: ["e8", "c8", "a8", "d8", "a8"],
  };
  return table[`${from}${to}`] || null;
}

function rookCastleEncoding(from, to, white) {
  return white ? ["h1e1", "a1e1"].includes(`${from}${to}`) : ["h8e8", "a8e8"].includes(`${from}${to}`);
}

function performCastle(castle, piece, suffix) {
  const [kingFrom, kingTo, rookFrom, rookTo, gateSquare] = castle;
  const white = piece === piece.toUpperCase();
  delete state.board[kingFrom];
  delete state.board[rookFrom];
  state.board[kingTo] = white ? "K" : "k";
  state.board[rookTo] = white ? "R" : "r";
  if (suffix === "h" || suffix === "e") state.board[gateSquare] = white ? suffix.toUpperCase() : suffix;
}

function promotedPiece(piece, to, suffix) {
  if (!suffix || !"qrbnhe".includes(suffix)) return piece;
  const isPawn = piece.toUpperCase() === "P";
  const lastRank = to[1] === "1" || to[1] === "8";
  if (!isPawn || !lastRank) return piece;
  return piece === piece.toUpperCase() ? suffix.toUpperCase() : suffix;
}

function isGateSuffix(suffix, from, piece, to) {
  if (suffix !== "h" && suffix !== "e") return false;
  if (piece.toUpperCase() === "P" && (to[1] === "1" || to[1] === "8")) return false;
  return from[1] === "1" || from[1] === "8";
}

function revealSolution() {
  const puzzle = currentPuzzle();
  if (!puzzle) return;
  solutionEl.classList.remove("hidden");
  const scores = puzzle.scores || {};
  const categories = puzzleCategoryLabels(puzzle);
  const line = puzzle.solution_line_san || (puzzle.solution || []).join(" ");
  const second = scores.second_san ? `${cp(scores.second_cp)} (${scores.second_san})` : cp(scores.second_cp);
  lineEl.innerHTML = `
    <div class="solution-row"><span class="solution-label">Correct move</span><span>${escapeHtml(puzzle.solution_san || (puzzle.solution || [])[0] || "-")}</span></div>
    <div class="solution-row"><span class="solution-label">Full line</span><span class="solution-line">${escapeHtml(line || "-")}</span></div>
  `;
  detailsEl.innerHTML = `
    <p>${escapeHtml(puzzle.reason || puzzle.kind || "Tactic")}.</p>
    <p>Best ${escapeHtml(cp(scores.best_cp))}, second ${escapeHtml(second)}.</p>
    ${categories.length ? `<div class="solution-label">Categories</div><ul class="category-list">${categories.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
  `;
  showAnalysisLink();
}

function puzzleCategoryLabels(puzzle) {
  const cats = puzzle.categories || {};
  return [cats.phase, cats.length, ...(cats.motifs || [])].filter(Boolean).map(labelText);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
function showAnalysisLink() {
  const puzzle = currentPuzzle();
  if (!puzzle) return;
  controls.analysis.href = pychessAnalysisUrl(puzzle.fen);
  controls.analysis.classList.remove("hidden");
}

function pychessAnalysisUrl(fen) {
  return `https://www.pychess.org/analysis/seirawan?fen=${encodeURIComponent((fen || "").replace(/\s+/g, "_"))}`;
}

function sourceText(puzzle) {
  const move = puzzle.move_number ? `move ${puzzle.move_number}` : "";
  const url = puzzle.source_url || "";
  return [url, move].filter(Boolean).join(" - ");
}

function cp(value) {
  return Number.isFinite(value) ? `${value} cp` : "n/a";
}

function setStatus(text, cls = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`.trim();
}

function inferPhase(puzzle) {
  const move = Number(puzzle.move_number || fenMoveNumber(puzzle.fen));
  if (move && move <= 12) return "opening";
  if (isEndgameFen(puzzle.fen)) return "endgame";
  return "middlegame";
}

function fenMoveNumber(fen) {
  const fields = (fen || "").split(/\s+/);
  return Number(fields[fields.length - 1] || 0);
}

function isEndgameFen(fen) {
  const board = ((fen || "").split(/\s+/)[0] || "").split("[")[0];
  const pieces = [...board].filter((ch) => /[A-Za-z]/.test(ch));
  const queens = pieces.filter((ch) => ch.toUpperCase() === "Q").length;
  const nonKingNonPawn = pieces.filter((ch) => !["K", "P"].includes(ch.toUpperCase())).length;
  return queens === 0 && nonKingNonPawn <= 4;
}

function inferLength(puzzle) {
  const plies = (puzzle.solution || []).length || 1;
  if (plies <= 1) return "one-move";
  if (plies <= 5) return "medium";
  return "long";
}

function inferMotifs(puzzle) {
  const tags = new Set(puzzle.tags || []);
  const motifs = new Set();
  const san = puzzle.solution_san || "";
  const first = (puzzle.solution || [""])[0] || "";
  if (puzzle.kind === "drawing") motifs.add("equality");
  if (puzzle.kind === "winning") motifs.add(scoreMotif(puzzle));
  if (tags.has("check-evasion")) motifs.add("defensive-move");
  if (tags.has("trivial-recapture") || tags.has("complex-recapture") || tags.has("recapture")) motifs.add("recapture");
  if (san.includes("#")) motifs.add("checkmate");
  if (san.includes("+") && !san.includes("#")) motifs.add("check");
  if (san.includes("=")) motifs.add("promotion");
  if (/[a-h][18][a-h][18][nbrqeh]/i.test(first)) motifs.add("promotion");
  if (san.includes("/H") || san.includes("/E") || /[HE]/.test(san)) motifs.add("fairy-piece");
  if (first.length >= 5 && (first[4] === "h" || first[4] === "e")) motifs.add("gating");
  if (san && !san.includes("x") && !san.includes("+") && !san.includes("#")) motifs.add("quiet-move");
  if (!motifs.size) motifs.add("advantage");
  return [...motifs].sort();
}

function scoreMotif(puzzle) {
  const score = puzzle.scores?.best_cp;
  if (Number.isFinite(score) && score >= 600) return "crushing";
  return "advantage";
}

function categorySummary(puzzle) {
  const cats = puzzle.categories || {};
  const motifs = (cats.motifs || []).map(labelText).join(", ");
  return `Categories: ${labelText(cats.phase)}, ${labelText(cats.length)}${motifs ? `, ${motifs}` : ""}. `;
}

function labelText(value) {
  return String(value || "")
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toggleCategoryFilters() {
  const hidden = controls.categoryOptions.classList.toggle("hidden");
  controls.categoryToggle.textContent = hidden ? "Filter by categories" : "Hide category filters";
}

function applySavedBoardTheme() {
  applyBoardTheme(localStorage.getItem("schess-board-theme") || "classic");
}

function applyBoardTheme(theme) {
  const selected = ["classic", "wood", "blue", "gray"].includes(theme) ? theme : "classic";
  document.body.dataset.boardTheme = selected;
  if (controls.boardTheme) controls.boardTheme.value = selected;
  localStorage.setItem("schess-board-theme", selected);
}
function applySavedTheme() {
  const saved = localStorage.getItem("schess-theme");
  const dark = saved ? saved === "dark" : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.body.classList.toggle("dark-mode", dark);
}

function toggleTheme() {
  const dark = !document.body.classList.contains("dark-mode");
  document.body.classList.toggle("dark-mode", dark);
  localStorage.setItem("schess-theme", dark ? "dark" : "light");
}

boot();
