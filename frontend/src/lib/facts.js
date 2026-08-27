// Fun facts shown while the agents work — kids read these instead of watching a spinner.
// Deliberately short, surprising, and true. No emojis: the UI uses drawn icons.

export const FUN_FACTS = [
  "A group of flamingos is called a 'flamboyance'.",
  "Honey never spoils. Archaeologists found 3,000-year-old honey that was still good.",
  "Octopuses have three hearts and blue blood.",
  "A day on Venus is longer than a whole year on Venus.",
  "Bananas are berries, but strawberries are not.",
  "Your bones are about four times stronger than concrete.",
  "Sharks existed before trees did.",
  "A single cloud can weigh more than a million kilograms.",
  "Butterflies taste with their feet.",
  "There are more stars in space than grains of sand on Earth.",
  "Wombat poop is cube-shaped.",
  "The Eiffel Tower gets taller in summer, because metal expands in heat.",
  "A snail can sleep for three years straight.",
  "Cows have best friends and get stressed when they are apart.",
  "Your nose can remember about 50,000 different smells.",
  "Sea otters hold hands while sleeping so they do not drift apart.",
  "The dot over a lowercase 'i' is called a tittle.",
  "Penguins propose to each other with a pebble.",
  "Hot water can freeze faster than cold water. Nobody fully knows why.",
  "An ant can lift about 50 times its own body weight.",
];

export function randomFact(exclude) {
  const pool = FUN_FACTS.filter((fact) => fact !== exclude);
  return pool[Math.floor(Math.random() * pool.length)];
}
