export type Species = {
  scientific_name: string;
  common_name_ru: string;
};

/** Источник будет GET /species, адрес не выдумывать. */
export function loadSpecies(): Promise<Species[]> {
  return Promise.resolve([]);
}
