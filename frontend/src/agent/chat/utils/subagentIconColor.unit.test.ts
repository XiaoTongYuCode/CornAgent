import { getColorContrastRatio, getSubagentIconColor } from './subagentIconColor'

it('keeps task colors stable and readable on light and dark surfaces', () => {
  for (const background of ['#ffffff', '#151618']) {
    for (let index = 0; index < 20; index++) {
      const seed = `task-${index}`
      const color = getSubagentIconColor(seed, background)
      expect(color).toBe(getSubagentIconColor(seed, background))
      expect(getColorContrastRatio(color!, background)).toBeGreaterThanOrEqual(4.5)
    }
  }
})
