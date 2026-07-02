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
  showHidden: document.getElementById("show-hidden"),
  showCheck: document.getElementById("show-check"),
  showRecapture: document.getElementById("show-recapture"),
};

async function boot() {
  try {
    const response = await fetch("public/puzzles.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.puzzles = payload.puzzles || [];
    applyFilters();
    bindControls();
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
  for (const input of [controls.showHidden, controls.showCheck, controls.showRecapture]) {
    input.addEventListener("change", applyFilters);
  }
}

function applyFilters() {
  state.filtered = state.puzzles.filter((puzzle) => {
    const tags = new Set(puzzle.tags || []);
    if (!controls.showHidden.checked && puzzle.hidden_by_default) return false;
    if (!controls.showCheck.checked && tags.has("check-evasion")) return false;
    if (!controls.showRecapture.checked && tags.has("trivial-recapture")) return false;
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
    setStatus("No puzzles match the current filters.", "bad");
    return;
  }
  state.board = parseFenBoard(puzzle.fen);
  state.orientation = puzzle.side || sideFromFen(puzzle.fen) || "w";
  state.selected = null;
  state.ply = 0;
  state.solved = false;
  solutionEl.classList.add("hidden");
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
    state.solved = true;
    setStatus("Solved.", "good");
    return;
  }
  if (state.ply % 2 === 1) {
    applyMove(line[state.ply]);
    state.ply += 1;
    renderBoard();
    if (state.ply >= line.length) {
      state.solved = true;
      setStatus("Solved.", "good");
    } else {
      setStatus("Continue the line.");
    }
  }
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
  const san = puzzle.solution_san ? `${puzzle.solution_san} ` : "";
  lineEl.textContent = `${san}${(puzzle.solution || []).join(" ")}`.trim();
  const scores = puzzle.scores || {};
  const tagText = (puzzle.tags || []).length ? `Tags: ${puzzle.tags.join(", ")}. ` : "";
  detailsEl.textContent = `${puzzle.reason || puzzle.kind || "Tactic"}. ${tagText}Best ${cp(scores.best_cp)}, second ${cp(scores.second_cp)}${scores.second_san ? ` (${scores.second_san})` : ""}.`;
}

function sourceText(puzzle) {
  const move = puzzle.move_number ? `move ${puzzle.move_number}` : "";
  const url = puzzle.source_url || "";
  return [url, move].filter(Boolean).join(" · ");
}

function cp(value) {
  return Number.isFinite(value) ? `${value} cp` : "n/a";
}

function setStatus(text, cls = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`.trim();
}

boot();
