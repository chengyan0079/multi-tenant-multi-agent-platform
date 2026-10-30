/** 列表统一排序：优先 updated_at 倒序，其次 create_at 倒序；时间相同按 id 升序。 */
export function sortByTimeThenId<T>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    const ta = ((a as any).updated_at || (a as any).create_at || '') as string;
    const tb = ((b as any).updated_at || (b as any).create_at || '') as string;
    if (ta !== tb) return tb < ta ? -1 : 1; // 时间倒序
    const ia = typeof (a as any).id === 'number' ? (a as any).id : 0;
    const ib = typeof (b as any).id === 'number' ? (b as any).id : 0;
    return ia - ib; // id 升序
  });
}
