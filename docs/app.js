const state = {
  puzzles: [],
  filtered: [],
  index: 0,
  board: {},
  selected: null,
  ply: 0,
  orientation: "w",
  solved: false,
  pendingChoice: null,
  dragFrom: null,
  showUnmoved: false,
  pocket: "",
  gatingSquares: new Set(),
  epSquare: "",
  openDetailFilter: "",
  matePlayOut: false,
  activeBaseSide: "",
  randomizeInitialPuzzle: false,
  puzzleSet: "full",
  curatedLevel: "beginner",
};

const files = ["a", "b", "c", "d", "e", "f", "g", "h"];
const hiddenTags = new Set(["standard-like", "trivial-recapture", "trivial-capture", "check-evasion", "manual-reject", "failed-reverify"]);
const defaultExcludedMotifs = new Set(["equality", "defensive-move"]);
const curatedLevels = {
  beginner: ["gnx85", "dkcpr", "cdkuv", "2ph2z"],
  "lower-intermediate": ["6rttj", "y37mv", "ue8pk", "sq7hh", "qngev", "ytxms"],
  "upper-intermediate": ["7x6sd", "xfgsk", "xhayk", "tphna"],
  advanced: ["qqn6r", "z8bt4", "d33pe"],
  expert: [],
};
const curatedPuzzleIds = new Set(Object.values(curatedLevels).flat());
const suggestionStorageKey = "schess-puzzle-suggestions";
const suggestionApiUrl = "https://schess-puzzle-suggestions.ft3g0.workers.dev/suggestions";
const boardEl = document.getElementById("board");
const counterEl = document.getElementById("counter");
const titleEl = document.getElementById("title");
const statusEl = document.getElementById("status");
const sourceEl = document.getElementById("source");
const solutionEl = document.getElementById("solution");
const lineEl = document.getElementById("line");
const detailsEl = document.getElementById("details");
const moveChoicesEl = document.getElementById("move-choices");
const reserveEl = document.getElementById("reserve");

const controls = {
  prev: document.getElementById("prev"),
  next: document.getElementById("next"),
  reset: document.getElementById("reset"),
  unmoved: document.getElementById("unmoved"),
  random: document.getElementById("random"),
  reveal: document.getElementById("reveal"),
  theme: document.getElementById("theme"),
  analysis: document.getElementById("analysis"),
  matePlayOut: document.getElementById("mate-playout"),
  setFull: document.getElementById("set-full"),
  setCurated: document.getElementById("set-curated"),
  curatedLevels: document.getElementById("curated-levels"),
  showHidden: document.getElementById("show-hidden"),
  hiddenOptions: document.getElementById("hidden-options"),
  standardFilters: document.getElementById("standard-filters"),
  showCheck: document.getElementById("show-check"),
  showRecapture: document.getElementById("show-recapture"),
  phase: document.getElementById("phase-filter"),
  phaseDetail: document.getElementById("phase-detail"),
  motif: document.getElementById("motif-filter"),
  motifDetail: document.getElementById("motif-detail"),
  length: document.getElementById("length-filter"),
  lengthDetail: document.getElementById("length-detail"),
  source: document.getElementById("source-filter"),
  categoryToggle: document.getElementById("category-toggle"),
  categoryOptions: document.getElementById("category-options"),
  boardTheme: document.getElementById("board-theme"),
  suggestToggle: document.getElementById("suggest-toggle"),
  suggestPanel: document.getElementById("suggest-panel"),
  suggestFen: document.getElementById("suggest-fen"),
  suggestNotes: document.getElementById("suggest-notes"),
  suggestSubmit: document.getElementById("suggest-submit"),
  suggestStatus: document.getElementById("suggest-status"),
};

async function boot() {
  applySavedTheme();
  applySavedBoardTheme();
  try {
    const response = await fetch("public/puzzles.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.puzzles = (payload.puzzles || []).map(enrichPuzzle);
    state.requestedPuzzleId = puzzleIdFromUrl();
    state.randomizeInitialPuzzle = !state.requestedPuzzleId;
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
  controls.unmoved.addEventListener("click", toggleUnmovedPieces);
  controls.random.addEventListener("click", () => gotoPuzzle(Math.floor(Math.random() * state.filtered.length)));
  controls.reveal.addEventListener("click", revealSolution);
  controls.matePlayOut.addEventListener("click", startMatePlayOut);
  controls.theme.addEventListener("click", toggleTheme);
  controls.categoryToggle.addEventListener("click", toggleCategoryFilters);
  controls.setFull.addEventListener("click", () => setPuzzleSet("full"));
  controls.setCurated.addEventListener("click", () => setPuzzleSet("curated"));
  controls.curatedLevels.querySelectorAll("[data-curated-level]").forEach((button) => {
    button.addEventListener("click", () => setCuratedLevel(button.dataset.curatedLevel));
  });
  controls.boardTheme.addEventListener("change", () => applyBoardTheme(controls.boardTheme.value));
  if (controls.suggestToggle && controls.suggestSubmit) {
    controls.suggestToggle.addEventListener("click", toggleSuggestionPanel);
    controls.suggestSubmit.addEventListener("click", submitSuggestion);
  }
  document.addEventListener("keydown", onKeyDown);
  document.addEventListener("click", onDocumentClick);
  for (const input of [controls.showHidden, controls.showCheck, controls.showRecapture, controls.phase, controls.motif, controls.length, controls.source]) {
    input.addEventListener("change", onFilterControlChanged);
  }
  for (const select of [controls.phase, controls.motif, controls.length]) {
    select.addEventListener("click", () => {
      if (select.value === "__detail") {
        state.openDetailFilter = detailGroupForSelect(select);
        updateDetailFilterVisibility();
      }
    });
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
      source: categories.source || inferSource(puzzle),
    },
  };
}

function populateCategoryFilters() {
  const phases = [...new Set(state.puzzles.map((p) => p.categories.phase).filter(Boolean))];
  const motifs = [...new Set(state.puzzles.flatMap((p) => p.categories.motifs || []))];
  const lengths = [...new Set(state.puzzles.map((p) => p.categories.length).filter(Boolean))];
  const sources = [...new Set(state.puzzles.map((p) => p.categories.source).filter(Boolean))];
  fillSelect(controls.phase, phases, ["opening", "middlegame", "endgame"], "All", true);
  fillSelect(controls.motif, motifs, [], "All", true);
  fillSelect(controls.length, lengths, ["one-move", "medium", "long"], "All", true);
  fillSelect(controls.source, sources, ["human-game", "engine-selfplay", "manual-suggestion"], "All", false);
  fillDetailOptions(controls.phaseDetail, phases, ["opening", "middlegame", "endgame"], "phase");
  fillDetailOptions(controls.motifDetail, motifs, [], "motif");
  fillDetailOptions(controls.lengthDetail, lengths, ["one-move", "medium", "long"], "length");
  applyMainstreamDefaultFilters();
}

function applyMainstreamDefaultFilters() {
  controls.length.value = "__detail";
  setDetailChecked(controls.lengthDetail, "one-move", false);
  controls.motif.value = "__detail";
  for (const motif of defaultExcludedMotifs) setDetailChecked(controls.motifDetail, motif, false);
  state.openDetailFilter = "";
  updateDetailFilterVisibility();
}

function setDetailChecked(container, value, checked) {
  if (!container) return;
  const input = [...container.querySelectorAll('input[type="checkbox"]')].find((box) => box.value === value);
  if (input) input.checked = checked;
}
function fillSelect(select, values, preferred = [], emptyLabel = "All", includeDetailed = false) {
  const current = select.value;
  const ordered = [...preferred.filter((value) => values.includes(value)), ...values.filter((value) => !preferred.includes(value)).sort()];
  select.innerHTML = `<option value="">${emptyLabel}</option>`;
  if (includeDetailed) {
    const detailed = document.createElement("option");
    detailed.value = "__detail";
    detailed.textContent = "Detailed inclusion/exclusion";
    select.appendChild(detailed);
  }
  for (const value of ordered) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelText(value);
    select.appendChild(option);
  }
  select.value = ordered.includes(current) || (includeDetailed && current === "__detail") ? current : "";
}


function fillDetailOptions(container, values, preferred = [], group) {
  const ordered = [...preferred.filter((value) => values.includes(value)), ...values.filter((value) => !preferred.includes(value)).sort()];
  container.innerHTML = "";
  const done = document.createElement("button");
  done.type = "button";
  done.className = "detail-toggle";
  done.textContent = "Done";
  done.addEventListener("click", () => closeDetailFilterForContainer(container));
  container.appendChild(done);
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "detail-toggle";
  toggle.textContent = "Toggle all";
  toggle.addEventListener("click", () => {
    const boxes = [...container.querySelectorAll('input[type="checkbox"]')];
    const next = !boxes.every((box) => box.checked);
    boxes.forEach((box) => { box.checked = next; });
    applyFilters();
  });
  container.appendChild(toggle);
  for (const value of ordered) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = true;
    checkbox.dataset.categoryGroup = group;
    checkbox.value = value;
    checkbox.addEventListener("change", applyFilters);
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(labelText(value)));
    container.appendChild(label);
  }
}

function onFilterControlChanged(event) {
  const select = event?.target;
  if (select?.value === "__detail") {
    state.openDetailFilter = detailGroupForSelect(select);
    resetDetailChecks(detailContainerForSelect(select), true);
  } else if ([controls.phase, controls.motif, controls.length].includes(select) && state.openDetailFilter === detailGroupForSelect(select)) {
    state.openDetailFilter = "";
  }
  updateDetailFilterVisibility();
  applyFilters();
}

function closeDetailFilterForContainer(container) {
  if (container === detailContainerForGroup(state.openDetailFilter)) {
    state.openDetailFilter = "";
  }
  updateDetailFilterVisibility();
}

function closeAllDetailFilters() {
  if (!state.openDetailFilter) return;
  state.openDetailFilter = "";
  updateDetailFilterVisibility();
}

function onDocumentClick(event) {
  if (!controls.categoryOptions || controls.categoryOptions.classList.contains("hidden")) return;
  if (controls.categoryOptions.contains(event.target)) return;
  closeAllDetailFilters();
}
function updateDetailFilterVisibility() {
  controls.phaseDetail.classList.toggle("hidden", !(controls.phase.value === "__detail" && state.openDetailFilter === "phase"));
  controls.motifDetail.classList.toggle("hidden", !(controls.motif.value === "__detail" && state.openDetailFilter === "motif"));
  controls.lengthDetail.classList.toggle("hidden", !(controls.length.value === "__detail" && state.openDetailFilter === "length"));
}

function detailGroupForSelect(select) {
  if (select === controls.phase) return "phase";
  if (select === controls.motif) return "motif";
  if (select === controls.length) return "length";
  return "";
}

function detailContainerForSelect(select) {
  return detailContainerForGroup(detailGroupForSelect(select));
}

function detailContainerForGroup(group) {
  if (group === "phase") return controls.phaseDetail;
  if (group === "motif") return controls.motifDetail;
  if (group === "length") return controls.lengthDetail;
  return null;
}

function resetDetailChecks(container, checked) {
  if (!container) return;
  container.querySelectorAll('input[type="checkbox"]').forEach((input) => { input.checked = checked; });
}

function checkedDetailValues(container) {
  return new Set([...container.querySelectorAll('input[type="checkbox"]:checked')].map((input) => input.value));
}
function setPuzzleSet(setName) {
  state.puzzleSet = setName === "curated" ? "curated" : "full";
  state.index = 0;
  state.randomizeInitialPuzzle = !state.requestedPuzzleId;
  applyFilters();
}

function setCuratedLevel(level) {
  state.curatedLevel = Object.hasOwn(curatedLevels, level) ? level : "beginner";
  state.index = 0;
  state.randomizeInitialPuzzle = !state.requestedPuzzleId;
  applyFilters();
}

function updatePuzzleSetTabs() {
  controls.setFull.classList.toggle("active", state.puzzleSet === "full");
  controls.setCurated.classList.toggle("active", state.puzzleSet === "curated");
  controls.curatedLevels.classList.toggle("hidden", state.puzzleSet !== "curated");
  controls.standardFilters.classList.toggle("hidden", state.puzzleSet === "curated");
  controls.categoryToggle.classList.toggle("hidden", state.puzzleSet === "curated");
  if (state.puzzleSet === "curated") controls.categoryOptions.classList.add("hidden");
  updateCuratedLevelTabs();
}

function updateCuratedLevelTabs() {
  controls.curatedLevels.querySelectorAll("[data-curated-level]").forEach((button) => {
    button.classList.toggle("active", button.dataset.curatedLevel === state.curatedLevel);
  });
}

function applyFilters() {
  controls.hiddenOptions.classList.toggle("hidden", !controls.showHidden.checked);
  updateDetailFilterVisibility();
  updatePuzzleSetTabs();
  const phaseSet = checkedDetailValues(controls.phaseDetail);
  const motifSet = checkedDetailValues(controls.motifDetail);
  const lengthSet = checkedDetailValues(controls.lengthDetail);
  state.filtered = state.puzzles.filter((puzzle) => {
    if (state.puzzleSet === "curated") {
      if (!(curatedLevels[state.curatedLevel] || []).includes(puzzle.id)) return false;
      return true;
    }
    const tags = new Set(puzzle.tags || []);
    const motifs = new Set(puzzle.categories.motifs || []);
    if (!controls.showHidden.checked && puzzle.hidden_by_default) return false;
    if (controls.showHidden.checked && !controls.showCheck.checked && tags.has("check-evasion")) return false;
    if (controls.showHidden.checked && !controls.showRecapture.checked && tags.has("trivial-recapture")) return false;

    if (controls.phase.value === "__detail") {
      if (!phaseSet.has(puzzle.categories.phase)) return false;
    } else if (controls.phase.value && puzzle.categories.phase !== controls.phase.value) {
      return false;
    }

    if (controls.motif.value === "__detail") {
      const puzzleMotifs = puzzle.categories.motifs || [];
      if (!puzzleMotifs.length || !puzzleMotifs.some((motif) => motifSet.has(motif))) return false;
      if (puzzleMotifs.some((motif) => !motifSet.has(motif))) return false;
    } else if (controls.motif.value && !motifs.has(controls.motif.value)) {
      return false;
    }

    if (controls.length.value === "__detail") {
      if (!lengthSet.has(puzzle.categories.length)) return false;
    } else if (controls.length.value && puzzle.categories.length !== controls.length.value) {
      return false;
    }

    if (controls.source.value && puzzle.categories.source !== controls.source.value) {
      return false;
    }

    return true;
  });
  const requested = state.requestedPuzzleId ? state.puzzles.find((puzzle) => puzzle.id === state.requestedPuzzleId) : null;
  if (requested) {
    const filteredIndex = state.filtered.findIndex((puzzle) => puzzle.id === requested.id);
    if (filteredIndex >= 0) {
      state.index = filteredIndex;
    } else {
      state.filtered = [requested];
      state.index = 0;
    }
    state.requestedPuzzleId = "";
  } else if (state.randomizeInitialPuzzle && state.filtered.length) {
    state.index = Math.floor(Math.random() * state.filtered.length);
    state.randomizeInitialPuzzle = false;
  } else {
    state.index = Math.min(state.index, Math.max(0, state.filtered.length - 1));
  }
  resetPuzzle();
  updatePuzzleUrl();
}

function currentPuzzle() {
  return state.filtered[state.index];
}

function gotoPuzzle(index) {
  if (!state.filtered.length) return;
  state.index = (index + state.filtered.length) % state.filtered.length;
  resetPuzzle();
  updatePuzzleUrl();
}

function puzzleIdFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return (params.get("p") || params.get("id") || window.location.hash.replace(/^#/, "")).trim();
}

function updatePuzzleUrl() {
  const puzzle = currentPuzzle();
  if (!puzzle?.id) return;
  const url = new URL(window.location.href);
  url.searchParams.set("p", puzzle.id);
  url.hash = "";
  window.history.replaceState(null, "", url);
}

function resetPuzzle() {
  const puzzle = currentPuzzle();
  if (!puzzle) {
    boardEl.innerHTML = "";
    state.pocket = "";
    state.gatingSquares = new Set();
    state.epSquare = "";
    renderReserve();
    counterEl.textContent = "0 / 0";
    titleEl.textContent = "No puzzles";
    sourceEl.textContent = "";
    solutionEl.classList.add("hidden");
    controls.analysis.classList.add("hidden");
    controls.matePlayOut.classList.add("hidden");
    clearMoveChoices();
    setStatus("No puzzles match the current filters.", "bad");
    return;
  }
  state.board = parseFenBoard(puzzle.fen);
  state.orientation = puzzle.side || sideFromFen(puzzle.fen) || "w";
  state.selected = null;
  state.ply = 0;
  state.solved = false;
  state.pocket = pocketFromFen(puzzle.fen);
  state.gatingSquares = gatingOptionSquaresFromFen(puzzle.fen);
  state.epSquare = epSquareFromFen(puzzle.fen);
  solutionEl.classList.add("hidden");
  controls.analysis.classList.add("hidden");
  controls.matePlayOut.classList.add("hidden");
  state.matePlayOut = false;
  state.activeBaseSide = puzzle.side || sideFromFen(puzzle.fen) || "w";
  counterEl.textContent = `${state.index + 1} / ${state.filtered.length}${puzzle.id ? `, ID: ${puzzle.id}` : ""}`;
  titleEl.textContent = `${puzzle.side === "b" ? "Black" : "White"} to move`;
  sourceEl.textContent = sourceText(puzzle);
  renderReserve();
  updateUnmovedButton();
  lineEl.textContent = "";
  detailsEl.textContent = "";
  clearMoveChoices();
  setBoardFeedback("");
  setStatus("Find the only move.");
  renderBoard();
}

function parseFenBoard(fen) {
  const placement = boardPlacement(fen);
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

function boardPlacement(fen) {
  return (((fen || "").split(/\s+/)[0] || "8/8/8/8/8/8/8/8").split("[")[0]) || "8/8/8/8/8/8/8/8";
}

function pocketFromFen(fen) {
  const placement = (fen || "").split(/\s+/)[0] || "";
  return (placement.match(/\[([^\]]*)\]/) || ["", ""])[1];
}
function sideFromFen(fen) {
  return (fen || "").split(/\s+/)[1];
}

function epSquareFromFen(fen) {
  const ep = (fen || "").split(/\s+/)[3] || "";
  return /^[a-h][36]$/.test(ep) ? ep : "";
}

function renderBoard() {
  boardEl.innerHTML = "";
  const optionSquares = visibleOptionSquares();
  const ranks = state.orientation === "b" ? [1,2,3,4,5,6,7,8] : [8,7,6,5,4,3,2,1];
  const visibleFiles = state.orientation === "b" ? [...files].reverse() : files;
  for (const rank of ranks) {
    for (const file of visibleFiles) {
      const square = `${file}${rank}`;
      const button = document.createElement("button");
      button.className = `square ${squareColor(square)}`;
      if (state.selected === square) button.classList.add("selected");
      const pendingSquares = pendingChoiceSquares();
      if (pendingSquares.from === square) button.classList.add("selected");
      if (pendingSquares.to === square) button.classList.add("choice-target");
      if (optionSquares.has(square)) button.classList.add("unmoved");
      button.dataset.square = square;
      button.addEventListener("click", () => onSquare(square));
      const piece = state.board[square];
      button.draggable = Boolean(piece) && !state.solved;
      button.addEventListener("dragstart", (event) => onDragStart(event, square));
      button.addEventListener("dragover", onDragOver);
      button.addEventListener("dragenter", (event) => onDragEnter(event, square));
      button.addEventListener("dragleave", onDragLeave);
      button.addEventListener("drop", (event) => onDrop(event, square));
      button.addEventListener("dragend", onDragEnd);
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

function renderReserve() {
  if (!reserveEl) return;
  const pocket = state.pocket || "";
  const white = [...pocket].filter((piece) => piece === "H" || piece === "E");
  const black = [...pocket].filter((piece) => piece === "h" || piece === "e");
  reserveEl.innerHTML = "";
  const title = document.createElement("div");
  title.className = "reserve-title";
  title.textContent = `Insert pieces (${white.length + black.length})`;
  reserveEl.appendChild(title);
  reserveEl.appendChild(reserveRow("White", white));
  reserveEl.appendChild(reserveRow("Black", black));
}

function reserveRow(label, pieces) {
  const row = document.createElement("div");
  row.className = "reserve-row";
  const name = document.createElement("span");
  name.className = "reserve-side";
  name.textContent = label;
  row.appendChild(name);
  const list = document.createElement("span");
  list.className = "reserve-list";
  if (!pieces.length) {
    const empty = document.createElement("span");
    empty.className = "reserve-empty";
    empty.textContent = "None";
    list.appendChild(empty);
  } else {
    for (const piece of pieces) list.appendChild(reserveChip(piece));
  }
  row.appendChild(list);
  return row;
}

function reserveChip(piece) {
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = `reserve-chip ${piece === piece.toUpperCase() ? "white-reserve" : "black-reserve"}`;
  const img = pieceImage(piece);
  chip.appendChild(img);
  const label = document.createElement("span");
  label.textContent = piece.toUpperCase() === "H" ? "Hawk" : "Elephant";
  chip.appendChild(label);
  const suffix = piece.toLowerCase();
  if (canChooseReservePiece(piece)) {
    chip.classList.add("choice-ready");
    chip.addEventListener("click", () => choosePendingSuffix(suffix));
  } else if (state.pendingChoice) {
    chip.disabled = true;
  }
  return chip;
}

function pendingChoiceSquares() {
  if (!state.pendingChoice) return {};
  const prefix = state.pendingChoice.userPrefix || "";
  return { from: prefix.slice(0, 2), to: prefix.slice(2, 4) };
}

function canChooseReservePiece(piece) {
  if (!state.pendingChoice) return false;
  const suffix = piece.toLowerCase();
  if (suffix !== "h" && suffix !== "e") return false;
  if (!state.pendingChoice.choices.some(([choiceSuffix]) => choiceSuffix === suffix)) return false;
  const from = state.pendingChoice.userPrefix.slice(0, 2);
  const moving = state.board[from];
  return Boolean(moving) && sameColor(piece, moving);
}

function toggleUnmovedPieces() {
  state.showUnmoved = !state.showUnmoved;
  updateUnmovedButton();
  renderBoard();
}

function updateUnmovedButton() {
  if (!controls.unmoved) return;
  controls.unmoved.classList.toggle("active", state.showUnmoved);
  const count = optionSquareCount();
  controls.unmoved.disabled = count === 0;
  if (count === 0) {
    controls.unmoved.textContent = "No castling/gating/en-passant options";
  } else {
    controls.unmoved.textContent = state.showUnmoved ? `Hide castling/gating/en-passant options (${count})` : `Castling/gating/en-passant options (${count})`;
  }
}

function visibleOptionSquares() {
  if (!state.showUnmoved) return new Set();
  const squares = new Set(state.gatingSquares || []);
  if (state.epSquare) squares.add(state.epSquare);
  return squares;
}

function optionSquareCount() {
  const squares = new Set(state.gatingSquares || []);
  if (state.epSquare) squares.add(state.epSquare);
  return squares.size;
}

function unmovedSquaresFromFen(fen) {
  const fields = (fen || "").split(/\s+/);
  const rights = fields[2] || "";
  const board = parseFenBoard(fen);
  const squares = new Set();
  for (const right of rights) {
    for (const square of squaresForRight(right)) {
      const piece = board[square];
      if (piece && piece.toUpperCase() !== "P") squares.add(square);
    }
  }
  return squares;
}

function squaresForRight(right) {
  if (right === "-") return [];
  if (right === "K") return ["e1", "h1"];
  if (right === "Q") return ["e1", "a1"];
  if (right === "k") return ["e8", "h8"];
  if (right === "q") return ["e8", "a8"];
  if (/^[A-H]$/.test(right)) return [`${right.toLowerCase()}1`];
  if (/^[a-h]$/.test(right)) return [`${right}8`];
  return [];
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

function onDragStart(event, square) {
  if (state.solved || !state.board[square]) {
    event.preventDefault();
    return;
  }
  state.dragFrom = square;
  state.selected = square;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", square);
  event.currentTarget.classList.add("dragging");
}

function onDragOver(event) {
  if (!state.dragFrom || state.solved) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
}

function onDragEnter(event, square) {
  if (!state.dragFrom || state.solved || state.dragFrom === square) return;
  event.currentTarget.classList.add("drag-target");
}

function onDragLeave(event) {
  event.currentTarget.classList.remove("drag-target");
}

function onDrop(event, square) {
  if (!state.dragFrom || state.solved) return;
  event.preventDefault();
  event.currentTarget.classList.remove("drag-target");
  const from = state.dragFrom || event.dataTransfer.getData("text/plain");
  state.dragFrom = null;
  state.selected = null;
  if (!from || from === square) {
    renderBoard();
    return;
  }
  tryUserMove(from, square);
}

function onDragEnd(event) {
  event.currentTarget.classList.remove("dragging");
  document.querySelectorAll(".drag-target").forEach((square) => square.classList.remove("drag-target"));
  if (!state.dragFrom) return;
  state.dragFrom = null;
  state.selected = null;
  renderBoard();
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
  const expected = activeLine()[state.ply];
  state.selected = null;
  clearMoveChoices();
  if (!expected) return;

  const userPrefix = `${from}${to}`;
  const matchesExpectedPrefix = moveMatchesPrefix(expected, userPrefix);
  const choices = matchesExpectedPrefix ? moveChoices(from, to, expected) : [];
  const suffixes = choices.length ? choices.map(([suffix]) => suffix) : [""];
  const hasLegalSuffix = suffixes.some((suffix) => isLegalUserMove(from, to, suffix));
  if (!hasLegalSuffix) {
    const side = currentSideToMove();
    const plausibleWrongMove = !matchesExpectedPrefix && isPseudoLegalMove(from, to) && !kingInCheck(state.board, side);
    if (!plausibleWrongMove) {
      setBoardFeedback("");
      setStatus("Illegal move.");
      renderBoard();
      return;
    }
  }

  if (!matchesExpectedPrefix) {
    setBoardFeedback("bad");
    setStatus(state.matePlayOut ? "That is not the fastest checkmate line." : "That is not the tactic move.", "bad");
    renderBoard();
    return;
  }

  if (choices.length) {
    showMoveChoices(userPrefix, expected, choices);
    renderBoard();
    renderReserve();
    return;
  }

  submitUserMove(expected);
}

function submitUserMove(move) {
  const puzzle = currentPuzzle();
  const expected = activeLine()[state.ply];
  const from = move.slice(0, 2);
  const to = move.slice(2, 4);
  const suffix = expectedSuffix(move);
  if (!isLegalUserMove(from, to, suffix)) {
    clearMoveChoices();
    setBoardFeedback("");
    setStatus("Illegal move.");
    renderBoard();
    renderReserve();
    return;
  }
  clearMoveChoices();
  if (!moveMatchesExpected(move, expected)) {
    setBoardFeedback("bad");
    setStatus(state.matePlayOut ? "That is not the fastest checkmate line." : "That is not the tactic move.", "bad");
    renderBoard();
    return;
  }
  applyMove(expected);
  renderReserve();
  state.ply += 1;
  setBoardFeedback("");
  setStatus("Correct.", "good");
  renderBoard();
  setTimeout(autoReplies, 250);
}

function moveMatchesExpected(move, expected) {
  return expectedSuffix(move) === expectedSuffix(expected) && moveMatchesPrefix(expected, move.slice(0, 4));
}
function moveMatchesPrefix(expected, userPrefix) {
  return movePrefixes(expected).includes(userPrefix);
}

function movePrefixes(move) {
  const prefix = move.slice(0, 4);
  const aliases = new Set([prefix]);
  const suffixless = move.slice(0, 4);
  const castleAliases = {
    e1g1: ["h1e1"],
    h1e1: ["e1g1"],
    e1c1: ["a1e1"],
    a1e1: ["e1c1"],
    e8g8: ["h8e8"],
    h8e8: ["e8g8"],
    e8c8: ["a8e8"],
    a8e8: ["e8c8"],
  };
  for (const item of castleAliases[suffixless] || []) aliases.add(item);
  return [...aliases];
}

function expectedSuffix(move) {
  return move.length > 4 ? move[4].toLowerCase() : "";
}

function currentSideToMove() {
  const puzzle = currentPuzzle();
  const initial = state.activeBaseSide || puzzle?.side || sideFromFen(puzzle?.fen || "") || "w";
  return state.ply % 2 === 0 ? initial : oppositeSide(initial);
}

function oppositeSide(side) {
  return side === "w" ? "b" : "w";
}

function pieceColor(piece) {
  return piece === piece.toUpperCase() ? "w" : "b";
}

function isLegalUserMove(from, to, suffix = "") {
  if (!isPseudoLegalMove(from, to)) return false;
  const piece = state.board[from];
  const side = pieceColor(piece);
  const nextBoard = boardAfterMove(state.board, from, to, suffix, piece);
  if (!nextBoard) return false;
  return !kingInCheck(nextBoard, side);
}

function boardAfterMove(board, from, to, suffix, piece) {
  const next = { ...board };
  const castle = castleMove(from, to, piece, suffix || "");
  if (castle) {
    const [kingFrom, kingTo, rookFrom, rookTo, gateSquare] = castle;
    const king = next[kingFrom];
    const rook = next[rookFrom];
    if (!king || !rook || king.toUpperCase() !== "K" || rook.toUpperCase() !== "R" || !sameColor(king, rook)) return null;
    const white = king === king.toUpperCase();
    delete next[kingFrom];
    delete next[rookFrom];
    next[kingTo] = white ? "K" : "k";
    next[rookTo] = white ? "R" : "r";
    if (suffix === "h" || suffix === "e") next[gateSquare] = white ? suffix.toUpperCase() : suffix;
    return next;
  }
  if (isEnPassantMove(from, to, piece)) delete next[enPassantCapturedSquare(to, piece)];
  delete next[from];
  next[to] = promotedPiece(piece, to, suffix || "");
  if (isGateSuffix(suffix || "", from, piece, to)) {
    next[from] = piece === piece.toUpperCase() ? suffix.toUpperCase() : suffix;
  }
  return next;
}

function kingInCheck(board, side) {
  const king = side === "w" ? "K" : "k";
  const kingSquare = Object.keys(board).find((square) => board[square] === king);
  if (!kingSquare) return false;
  return isSquareAttacked(board, kingSquare, oppositeSide(side));
}

function isSquareAttacked(board, square, attackerSide) {
  return Object.entries(board).some(([from, piece]) => pieceColor(piece) === attackerSide && attacksSquare(board, from, square, piece));
}

function attacksSquare(board, from, to, piece) {
  if (from === to) return false;
  const dx = files.indexOf(to[0]) - files.indexOf(from[0]);
  const dy = Number(to[1]) - Number(from[1]);
  const adx = Math.abs(dx);
  const ady = Math.abs(dy);
  const role = piece.toUpperCase();
  const forward = piece === piece.toUpperCase() ? 1 : -1;
  if (role === "P") return adx === 1 && dy === forward;
  if (role === "N") return isKnightStep(adx, ady);
  if (role === "B") return isDiagonal(adx, ady) && isPathClearOnBoard(board, from, to);
  if (role === "R") return isStraight(adx, ady) && isPathClearOnBoard(board, from, to);
  if (role === "Q") return (isStraight(adx, ady) || isDiagonal(adx, ady)) && isPathClearOnBoard(board, from, to);
  if (role === "K") return Math.max(adx, ady) === 1;
  if (role === "H") return isKnightStep(adx, ady) || (isDiagonal(adx, ady) && isPathClearOnBoard(board, from, to));
  if (role === "E") return isKnightStep(adx, ady) || (isStraight(adx, ady) && isPathClearOnBoard(board, from, to));
  return false;
}

function isPathClearOnBoard(board, from, to) {
  const dx = Math.sign(files.indexOf(to[0]) - files.indexOf(from[0]));
  const dy = Math.sign(Number(to[1]) - Number(from[1]));
  let fileIndex = files.indexOf(from[0]) + dx;
  let rank = Number(from[1]) + dy;
  while (`${files[fileIndex]}${rank}` !== to) {
    if (board[`${files[fileIndex]}${rank}`]) return false;
    fileIndex += dx;
    rank += dy;
  }
  return true;
}
function isPseudoLegalMove(from, to) {
  const piece = state.board[from];
  if (!piece || from === to || !isBoardSquare(from) || !isBoardSquare(to)) return false;
  const side = currentSideToMove();
  if (side && pieceColor(piece) !== side) return false;
  const dx = files.indexOf(to[0]) - files.indexOf(from[0]);
  const dy = Number(to[1]) - Number(from[1]);
  const adx = Math.abs(dx);
  const ady = Math.abs(dy);
  const role = piece.toUpperCase();
  const forward = piece === piece.toUpperCase() ? 1 : -1;

  if (isCastleMovePrefix(`${from}${to}`)) return role === "K" || role === "R";
  const target = state.board[to];
  if (target && sameColor(piece, target)) return false;
  if (role === "P") {
    const startRank = piece === piece.toUpperCase() ? "2" : "7";
    if (dx === 0 && dy === forward && !target) return true;
    if (dx === 0 && dy === 2 * forward && from[1] === startRank && !target && !state.board[`${from[0]}${Number(from[1]) + forward}`]) return true;
    if (adx === 1 && dy === forward && Boolean(target) && !sameColor(piece, target)) return true;
    return isEnPassantMove(from, to, piece);
  }
  if (role === "N") return isKnightStep(adx, ady);
  if (role === "B") return isDiagonal(adx, ady) && isPathClear(from, to);
  if (role === "R") return isStraight(adx, ady) && isPathClear(from, to);
  if (role === "Q") return (isStraight(adx, ady) || isDiagonal(adx, ady)) && isPathClear(from, to);
  if (role === "K") return Math.max(adx, ady) === 1;
  if (role === "H") return isKnightStep(adx, ady) || (isDiagonal(adx, ady) && isPathClear(from, to));
  if (role === "E") return isKnightStep(adx, ady) || (isStraight(adx, ady) && isPathClear(from, to));
  return false;
}

function isBoardSquare(square) {
  return /^[a-h][1-8]$/.test(square || "");
}

function sameColor(a, b) {
  return (a === a.toUpperCase()) === (b === b.toUpperCase());
}

function isEnPassantMove(from, to, piece) {
  if (!piece || piece.toUpperCase() !== "P" || !state.epSquare || to !== state.epSquare) return false;
  if (state.board[to]) return false;
  const dx = Math.abs(files.indexOf(to[0]) - files.indexOf(from[0]));
  const dy = Number(to[1]) - Number(from[1]);
  const forward = piece === piece.toUpperCase() ? 1 : -1;
  const captured = state.board[enPassantCapturedSquare(to, piece)];
  return dx === 1 && dy === forward && Boolean(captured) && captured.toUpperCase() === "P" && !sameColor(piece, captured);
}

function enPassantCapturedSquare(to, piece) {
  const forward = piece === piece.toUpperCase() ? 1 : -1;
  return `${to[0]}${Number(to[1]) - forward}`;
}

function isKnightStep(adx, ady) {
  return (adx === 1 && ady === 2) || (adx === 2 && ady === 1);
}

function isStraight(adx, ady) {
  return (adx === 0) !== (ady === 0);
}

function isDiagonal(adx, ady) {
  return adx === ady && adx > 0;
}

function isPathClear(from, to) {
  const dx = Math.sign(files.indexOf(to[0]) - files.indexOf(from[0]));
  const dy = Math.sign(Number(to[1]) - Number(from[1]));
  let fileIndex = files.indexOf(from[0]) + dx;
  let rank = Number(from[1]) + dy;
  while (`${files[fileIndex]}${rank}` !== to) {
    if (state.board[`${files[fileIndex]}${rank}`]) return false;
    fileIndex += dx;
    rank += dy;
  }
  return true;
}

function moveChoices(from, to, expected) {
  const piece = state.board[from];
  const suffix = expectedSuffix(expected);
  if (piece && piece.toUpperCase() === "P" && (to[1] === "1" || to[1] === "8")) {
    return [
      ["q", "Queen", "Q"],
      ["r", "Rook", "R"],
      ["b", "Bishop", "B"],
      ["n", "Knight", "N"],
      ["h", "Hawk", "H"],
      ["e", "Elephant", "E"],
    ];
  }
  if (gatingAvailable(from, to, expected)) {
    return [["", "No insert", "Enter"], ["h", "Hawk", "H"], ["e", "Elephant", "E"]];
  }
  if (suffix) return [[suffix, suffix.toUpperCase(), suffix.toUpperCase()]];
  return [];
}

function gatingAvailable(from, to, expected) {
  const piece = state.board[from];
  if (!piece) return false;
  if (piece.toUpperCase() === "P" && (to[1] === "1" || to[1] === "8")) return false;

  const color = piece === piece.toUpperCase() ? "w" : "b";
  if (!pocketHasGatePiece(color)) return false;
  return state.gatingSquares.has(from) || castleGateOptionMatches(`${from}${to}`);
}

function gatingOptionSquaresFromFen(fen) {
  const fields = (fen || "").split(/\s+/);
  const rights = fields[2] || "";
  const board = parseFenBoard(fen);
  const squares = new Set();
  for (const right of rights) {
    for (const square of squaresForRight(right)) {
      const piece = board[square];
      if (piece && piece.toUpperCase() !== "P") squares.add(square);
    }
  }
  return squares;
}

function castleGateOptionMatches(prefix) {
  const optionSquares = state.gatingSquares;
  const castleSources = {
    e1g1: ["e1", "h1"],
    h1e1: ["e1", "h1"],
    e1c1: ["e1", "a1"],
    a1e1: ["e1", "a1"],
    e8g8: ["e8", "h8"],
    h8e8: ["e8", "h8"],
    e8c8: ["e8", "a8"],
    a8e8: ["e8", "a8"],
  };
  return (castleSources[prefix] || []).some((square) => optionSquares.has(square));
}

function pocketHasGatePiece(color) {
  const pieces = color === "w" ? "HE" : "he";
  return [...(state.pocket || "")].some((piece) => pieces.includes(piece));
}


function isCastleMovePrefix(prefix) {
  return ["e1g1", "h1e1", "e1c1", "a1e1", "e8g8", "h8e8", "e8c8", "a8e8"].includes(prefix);
}

function showMoveChoices(userPrefix, expected, choices) {
  state.pendingChoice = { userPrefix, expected, choices };
  moveChoicesEl.innerHTML = "";
  const label = document.createElement("span");
  label.className = "move-choice-label";
  label.textContent = choices.some(([suffix]) => suffix === "") ? "Insert" : "Choose piece";
  moveChoicesEl.appendChild(label);
  for (const [suffix, labelText, hotkey] of choices) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `${escapeHtml(labelText)} <kbd>${escapeHtml(hotkey)}</kbd>`;
    button.addEventListener("click", () => submitUserMove(expectedWithUserPrefix(expected, userPrefix, suffix)));
    moveChoicesEl.appendChild(button);
  }
  moveChoicesEl.classList.remove("hidden");
  renderReserve();
  setStatus(choices.some(([suffix]) => suffix === "") ? "Choose insertion: H, E, or Enter for none." : "Choose the promoted piece.");
}

function expectedWithUserPrefix(expected, userPrefix, suffix) {
  const expectedPrefix = expected.slice(0, 4);
  if (userPrefix === expectedPrefix) return `${expectedPrefix}${suffix}`;
  return `${userPrefix}${suffix}`;
}

function clearMoveChoices() {
  state.pendingChoice = null;
  moveChoicesEl.innerHTML = "";
  moveChoicesEl.classList.add("hidden");
  renderReserve();
}

function onKeyDown(event) {
  if (event.key === "Escape" && state.openDetailFilter) {
    event.preventDefault();
    closeAllDetailFilters();
    return;
  }
  if (!state.pendingChoice || moveChoicesEl.classList.contains("hidden")) return;
  const key = event.key.toLowerCase();
  const choice = state.pendingChoice.choices.find(([suffix, , hotkey]) => {
    if (hotkey.toLowerCase() === "enter") return key === "enter";
    return hotkey.toLowerCase() === key;
  });
  if (!choice) return;

  event.preventDefault();
  const [suffix] = choice;
  choosePendingSuffix(suffix);
}

function choosePendingSuffix(suffix) {
  if (!state.pendingChoice) return;
  submitUserMove(expectedWithUserPrefix(state.pendingChoice.expected, state.pendingChoice.userPrefix, suffix));
}
function autoReplies() {
  const puzzle = currentPuzzle();
  if (!puzzle) return;
  const line = activeLine();
  if (state.ply >= line.length) {
    finishActiveLine();
    return;
  }
  if (state.ply % 2 === 1) {
    applyMove(line[state.ply]);
    renderReserve();
    state.ply += 1;
    renderBoard();
    if (state.ply >= line.length) {
      finishActiveLine();
    } else {
      setStatus("Continue the line.");
    }
  }
}


function activeLine() {
  const puzzle = currentPuzzle();
  if (!puzzle) return [];
  return state.matePlayOut ? (puzzle.mate_line || []) : (puzzle.solution || []);
}

function finishActiveLine() {
  if (state.matePlayOut) {
    state.solved = true;
    setBoardFeedback("good");
    setStatus("Checkmate complete.", "good");
    showAnalysisLink();
    return;
  }
  markSolved();
}

function showMatePlayOutButton() {
  const puzzle = currentPuzzle();
  if (!puzzle || !(puzzle.mate_line || []).length || !puzzle.mate_start_fen || state.matePlayOut) return;
  controls.matePlayOut.classList.remove("hidden");
}

function startMatePlayOut() {
  const puzzle = currentPuzzle();
  if (!puzzle || !(puzzle.mate_line || []).length || !puzzle.mate_start_fen) return;
  const startFen = puzzle.mate_start_fen;
  state.board = parseFenBoard(startFen);
  state.orientation = puzzle.side || sideFromFen(puzzle.fen) || "w";
  state.selected = null;
  state.ply = 0;
  state.solved = false;
  state.matePlayOut = true;
  state.pocket = pocketFromFen(startFen);
  state.gatingSquares = gatingOptionSquaresFromFen(startFen);
  state.epSquare = epSquareFromFen(startFen);
  state.activeBaseSide = sideFromFen(startFen) || puzzle.side || "w";
  clearMoveChoices();
  controls.matePlayOut.classList.add("hidden");
  setBoardFeedback("");
  setStatus("Play the fastest checkmate line.");
  renderReserve();
  renderBoard();
  autoStartMateDefense();
}


function autoStartMateDefense() {
  const puzzle = currentPuzzle();
  const line = puzzle?.mate_line || [];
  if (!state.matePlayOut || !line.length) return;
  if (currentSideToMove() === puzzle.side) return;
  applyMove(line[state.ply]);
  renderReserve();
  state.ply += 1;
  renderBoard();
  setStatus("Find the fastest checkmate continuation.");
}

function bonusMateAlternativeMatches(userPrefix) {
  const puzzle = currentPuzzle();
  if (!state.matePlayOut || !puzzle || currentSideToMove() !== puzzle.side) return false;
  return (puzzle.mate_alternative_first_moves || []).some((move) => moveMatchesPrefix(move.uci || "", userPrefix));
}

function markSolved() {
  state.solved = true;
  setBoardFeedback("good");
  setStatus("Solved.", "good");
  showAnalysisLink();
  showMatePlayOutButton();
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
    deactivateCastleGating(castle);
    if (suffix === "h" || suffix === "e") removePocketPiece(pieceColor(piece), suffix);
    return;
  }

  if (isEnPassantMove(from, to, piece)) delete state.board[enPassantCapturedSquare(to, piece)];
  delete state.board[from];
  state.board[to] = promotedPiece(piece, to, suffix);
  state.gatingSquares.delete(from);
  if (isGateSuffix(suffix, from, piece, to)) {
    state.board[from] = piece === piece.toUpperCase() ? suffix.toUpperCase() : suffix;
    removePocketPiece(pieceColor(piece), suffix);
  }
}

function deactivateCastleGating(castle) {
  const [kingFrom, , rookFrom] = castle;
  state.gatingSquares.delete(kingFrom);
  state.gatingSquares.delete(rookFrom);
}

function removePocketPiece(color, suffix) {
  const wanted = color === "w" ? suffix.toUpperCase() : suffix.toLowerCase();
  const pieces = [...(state.pocket || "")];
  const index = pieces.indexOf(wanted);
  if (index >= 0) pieces.splice(index, 1);
  state.pocket = pieces.join("");
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
  showMatePlayOutButton();
  const scores = puzzle.scores || {};
  const categories = puzzleCategoryLabels(puzzle);
  const line = puzzle.solution_line_san || (puzzle.solution || []).join(" ");
  const second = scores.second_san ? `${cp(scores.second_cp)} (${scores.second_san})` : cp(scores.second_cp);
  lineEl.innerHTML = `
    <div class="solution-row"><span class="solution-label">Correct move</span><span>${escapeHtml(puzzle.solution_san || (puzzle.solution || [])[0] || "-")}</span></div>
    <div class="solution-row"><span class="solution-label">Full line</span><span class="solution-line">${escapeHtml(line || "-")}</span></div>
    <div class="solution-row"><span class="solution-label">FEN</span><span class="solution-line">${escapeHtml(puzzle.fen || "-")}</span></div>
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
  return [cats.phase, cats.length, cats.source, ...(cats.motifs || [])].filter(Boolean).map(labelText);
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

function setBoardFeedback(kind) {
  boardEl.classList.toggle("feedback-good", kind === "good");
  boardEl.classList.toggle("feedback-bad", kind === "bad");
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

function inferSource(puzzle) {
  const source = String(puzzle.source_url || "").toLowerCase();
  if (source.includes("chess.com") || source.includes("pychess.org")) return "human-game";
  if (source.includes("selfplay") || source.includes("local-selfplay")) return "engine-selfplay";
  return "manual-suggestion";
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
  const fullLineSan = puzzle.solution_line_san || "";
  const bestScore = puzzle.scores?.best_cp;
  const isMateScore = Number.isFinite(bestScore) && bestScore >= 90000;
  if (san.includes("#") || fullLineSan.includes("#") || isMateScore) motifs.add("checkmate");
  if (san.includes("+") && !san.includes("#") && !isMateScore) motifs.add("check");
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
  return `Categories: ${labelText(cats.phase)}, ${labelText(cats.length)}, ${labelText(cats.source)}${motifs ? `, ${motifs}` : ""}. `;
}

function labelText(value) {
  return String(value || "")
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toggleSuggestionPanel() {
  controls.suggestPanel.classList.toggle("hidden");
  if (!controls.suggestPanel.classList.contains("hidden")) controls.suggestFen.focus();
}

async function submitSuggestion() {
  const fen = controls.suggestFen.value.trim();
  const notes = controls.suggestNotes.value.trim();
  if (!fen) {
    setSuggestionStatus("Please enter a FEN first.", "bad");
    return;
  }
  if (!looksLikeFen(fen)) {
    setSuggestionStatus("This does not look like a full FEN yet.", "bad");
    return;
  }
  const suggestion = {
    fen,
    notes,
    page: window.location.href,
    website: "",
    created_at: new Date().toISOString(),
  };
  controls.suggestSubmit.disabled = true;
  setSuggestionStatus("Sending suggestion...", "");
  try {
    const response = await fetch(suggestionApiUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(suggestion),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    const suggestions = readSuggestions();
    suggestions.push({ ...suggestion, remote_id: payload.id });
    localStorage.setItem(suggestionStorageKey, JSON.stringify(suggestions));
    setSuggestionStatus("Suggestion sent. Thank you!", "good");
    controls.suggestFen.value = "";
    controls.suggestNotes.value = "";
  } catch (error) {
    setSuggestionStatus(`Could not send suggestion: ${error.message}`, "bad");
  } finally {
    controls.suggestSubmit.disabled = false;
  }
}

function looksLikeFen(fen) {
  const fields = fen.split(/\s+/);
  return fields.length >= 6 && fields[0].includes("/") && /^[wb]$/.test(fields[1]);
}

function readSuggestions() {
  try {
    const parsed = JSON.parse(localStorage.getItem(suggestionStorageKey) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function githubSuggestionUrl(suggestion) {
  const body = [
    "Suggested S-Chess puzzle candidate",
    "",
    `FEN: ${suggestion.fen}`,
    "",
    suggestion.notes ? `Notes: ${suggestion.notes}` : "Notes:",
    "",
    `Submitted from: ${suggestion.page}`,
  ].join("\n");
  const params = new URLSearchParams({ title: "Puzzle suggestion", body });
  return `https://github.com/fT3g0/schess-puzzles/issues/new?${params.toString()}`;
}

function setSuggestionStatus(text, cls = "") {
  controls.suggestStatus.textContent = text;
  controls.suggestStatus.className = `suggest-status ${cls}`.trim();
}
function toggleCategoryFilters() {
  const hidden = controls.categoryOptions.classList.toggle("hidden");
  controls.categoryToggle.textContent = hidden ? "Filter by categories" : "Hide category filters";
}

function applySavedBoardTheme() {
  const versionKey = "schess-board-theme-default-version";
  let saved = localStorage.getItem("schess-board-theme");
  if (localStorage.getItem(versionKey) !== "wood-default" && (!saved || saved === "classic")) {
    saved = "wood";
    localStorage.setItem(versionKey, "wood-default");
  }
  applyBoardTheme(saved || "wood");
}

function applyBoardTheme(theme) {
  const selected = ["wood", "wood-muted", "classic", "blue", "gray"].includes(theme) ? theme : "wood";
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
