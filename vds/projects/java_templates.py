"""Dateien der Spring-Boot-Vorlage (Maven mit eigenem Wrapper-Skript). Platzhalter: __NAME__, __IDLOWER__ (Java-Paketname)."""

SPRING_BOOT = "4.1.2"
MAVEN = "3.9.9"

POM = f'''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>

  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>{SPRING_BOOT}</version>
    <relativePath/>
  </parent>

  <groupId>com.example</groupId>
  <artifactId>__IDLOWER__</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <name>__NAME__</name>

  <properties>
    <java.version>21</java.version>
  </properties>

  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-webmvc</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-webmvc-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
'''

MVNW = f'''#!/bin/sh
# Maven-Wrapper: lädt Maven {MAVEN} beim ersten Aufruf nach ~/.m2/wrapper und startet es – Maven muss nicht installiert sein.
set -e
VERSION="{MAVEN}"
DIR="${{MAVEN_USER_HOME:-$HOME/.m2}}/wrapper/dists/apache-maven-$VERSION"
if [ ! -x "$DIR/bin/mvn" ]; then
  URL="https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/$VERSION/apache-maven-$VERSION-bin.tar.gz"
  echo "Lade Maven $VERSION …" >&2
  mkdir -p "$DIR.tmp"
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$URL" | tar -xz -C "$DIR.tmp" --strip-components=1
  else wget -qO- "$URL" | tar -xz -C "$DIR.tmp" --strip-components=1; fi
  rm -rf "$DIR" && mv "$DIR.tmp" "$DIR"
fi
exec "$DIR/bin/mvn" "$@"
'''

APP = '''package com.example.__IDLOWER__;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class Application {

    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
'''

CONTROLLER = '''package com.example.__IDLOWER__;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HelloController {

    @GetMapping("/api/hello")
    public Map<String, String> hello(@RequestParam(defaultValue = "Welt") String name) {
        return Map.of("message", "Hallo, " + name + "!");
    }
}
'''

TEST = '''package com.example.__IDLOWER__;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class HelloControllerTests {

    @Autowired
    private MockMvc mvc;

    @Test
    void sagtHallo() throws Exception {
        mvc.perform(get("/api/hello").param("name", "Peter"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.message").value("Hallo, Peter!"));
    }
}
'''

INDEX = '''<!doctype html>
<html lang="de">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__NAME__</title>
    <style>
      body { font-family: system-ui, sans-serif; padding: 24px; }
      button { padding: 6px 14px; }
    </style>
  </head>
  <body>
    <h1>__NAME__</h1>
    <p>Spring Boot läuft. Die Antwort kommt von <code>/api/hello</code>:</p>
    <input id="name" value="Welt" />
    <button id="go">Hallo sagen</button>
    <p id="out"></p>
    <script>
      document.getElementById("go").onclick = async () => {
        const r = await fetch("/api/hello?name=" + encodeURIComponent(document.getElementById("name").value));
        document.getElementById("out").textContent = (await r.json()).message;
      };
    </script>
  </body>
</html>
'''

SPRING_FILES = {
    "pom.xml": POM,
    "mvnw": MVNW,
    "src/main/java/com/example/__IDLOWER__/Application.java": APP,
    "src/main/java/com/example/__IDLOWER__/HelloController.java": CONTROLLER,
    "src/test/java/com/example/__IDLOWER__/HelloControllerTests.java": TEST,
    "src/main/resources/static/index.html": INDEX,
    "src/main/resources/application.properties": "spring.application.name=__NAME__\nserver.port=8080\n",
}
