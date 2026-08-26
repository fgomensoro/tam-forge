import { render, screen } from "@testing-library/react";
import { App } from "../src/App";

it("renders the private TAM Forge shell in English", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "TAM Forge" })).toBeVisible();
  expect(screen.getByText("Loading your study workspace…")).toBeVisible();
});
