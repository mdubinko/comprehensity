/*
 * Sample Java file used as a parser test fixture.
 *
 * Covers: java.* / javax.* (SYSTEM), well-known org.* / com.* / io.* (EXTERNAL),
 *         wildcard imports, static imports, and local package imports.
 */
import java.util.List;
import java.util.Map;
import java.util.*;
import javax.servlet.http.HttpServlet;

import org.springframework.stereotype.Service;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import com.google.gson.Gson;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.grpc.Channel;
import io.micrometer.core.instrument.MeterRegistry;

import static org.junit.Assert.assertEquals;

import com.example.myapp.core.BaseService;
import com.example.myapp.util.Validator;

public class Sample {
    private final Logger log = null;

    public void run() {
        List<String> items = new java.util.ArrayList<>();
        assertEquals("x", "x");
    }
}
