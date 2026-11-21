/** A small, deterministic force-directed layout for the dependency graph. */

export interface LayoutInput {
  id: string;
  weight: number;
}

export interface Point {
  x: number;
  y: number;
}

const REPULSION = 2600;
const SPRING = 0.02;
const SPRING_LENGTH = 90;
const GRAVITY = 0.012;
const DAMPING = 0.82;

/**
 * Place nodes in a `size` × `size` box. Connected nodes pull together, every pair
 * pushes apart, and a weak pull to the centre keeps islands on screen. Starting
 * positions come from the node order, so the same graph always looks the same.
 */
export function forceLayout(
  nodes: LayoutInput[],
  edges: { source: string; target: string }[],
  size = 600,
  iterations = 260,
): Map<string, Point> {
  const centre = size / 2;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const positions = nodes.map((_, i) => {
    // A golden-angle spiral spreads nodes evenly without randomness.
    const angle = i * 2.399963;
    const radius = 18 * Math.sqrt(i + 1);
    return { x: centre + radius * Math.cos(angle), y: centre + radius * Math.sin(angle) };
  });
  const velocity = nodes.map(() => ({ x: 0, y: 0 }));
  const links = edges
    .map((edge) => [index.get(edge.source), index.get(edge.target)] as const)
    .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined);

  // Unconnected nodes have no springs to hold them, so they get a stronger pull to
  // the centre instead of drifting to the edges and shrinking everything else.
  const linked = new Set(links.flat());
  for (let step = 0; step < iterations; step += 1) {
    const cooling = 1 - step / iterations;
    const force = positions.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < positions.length; i += 1) {
      for (let j = i + 1; j < positions.length; j += 1) {
        const dx = positions[i].x - positions[j].x;
        const dy = positions[i].y - positions[j].y;
        const distanceSq = Math.max(dx * dx + dy * dy, 25);
        const push = REPULSION / distanceSq;
        const distance = Math.sqrt(distanceSq);
        force[i].x += (dx / distance) * push;
        force[i].y += (dy / distance) * push;
        force[j].x -= (dx / distance) * push;
        force[j].y -= (dy / distance) * push;
      }
    }
    for (const [a, b] of links) {
      const dx = positions[b].x - positions[a].x;
      const dy = positions[b].y - positions[a].y;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const pull = SPRING * (distance - SPRING_LENGTH);
      force[a].x += (dx / distance) * pull;
      force[a].y += (dy / distance) * pull;
      force[b].x -= (dx / distance) * pull;
      force[b].y -= (dy / distance) * pull;
    }
    for (let i = 0; i < positions.length; i += 1) {
      const pull = GRAVITY * (1 + nodes[i].weight * 0.05) * (linked.has(i) ? 1 : 3.5);
      force[i].x += (centre - positions[i].x) * pull;
      force[i].y += (centre - positions[i].y) * pull;
      velocity[i].x = (velocity[i].x + force[i].x) * DAMPING * cooling;
      velocity[i].y = (velocity[i].y + force[i].y) * DAMPING * cooling;
      positions[i].x += velocity[i].x;
      positions[i].y += velocity[i].y;
    }
  }

  // Fit the result into the box with a margin.
  const margin = 70;
  const xs = positions.map((p) => p.x);
  const ys = positions.map((p) => p.y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min((size - 2 * margin) / Math.max(maxX - minX, 1), (size - 2 * margin) / Math.max(maxY - minY, 1), 2.4);
  const offsetX = (size - (maxX - minX) * scale) / 2;
  const offsetY = (size - (maxY - minY) * scale) / 2;
  return new Map(
    nodes.map((node, i) => [
      node.id,
      { x: offsetX + (positions[i].x - minX) * scale, y: offsetY + (positions[i].y - minY) * scale },
    ]),
  );
}

/** Every node reachable downstream of `start`: its blast radius. */
export function downstream(start: string, edges: { source: string; target: string }[]): Set<string> {
  const next = new Map<string, string[]>();
  for (const edge of edges) next.set(edge.source, [...(next.get(edge.source) ?? []), edge.target]);
  const seen = new Set<string>();
  const queue = [start];
  while (queue.length) {
    const node = queue.shift()!;
    for (const target of next.get(node) ?? []) {
      if (!seen.has(target) && target !== start) {
        seen.add(target);
        queue.push(target);
      }
    }
  }
  return seen;
}
