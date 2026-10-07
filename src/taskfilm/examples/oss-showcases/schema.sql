CREATE TABLE "users" (
  "id" INTEGER PRIMARY KEY,
  "name" VARCHAR(80) NOT NULL
);

CREATE TABLE "projects" (
  "id" INTEGER PRIMARY KEY,
  "owner_id" INTEGER NOT NULL,
  "title" VARCHAR(120) NOT NULL,
  FOREIGN KEY ("owner_id") REFERENCES "users"("id")
);
